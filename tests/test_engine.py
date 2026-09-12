"""Registry selection, capability behaviour, and the orchestrated run."""

from __future__ import annotations

from datetime import timedelta

import pytest

from ironclad import registry
from ironclad.base import AssessmentContext, AssessmentModule, Finding, ModuleResult
from ironclad.engine import merge_consensus, run_assessment
from ironclad.errors import SelectionError
from ironclad.model.assessment import ControlStatus
from ironclad.model.control import Framework
from ironclad.model.evidence import EvidenceSet, LinkMethod
from ironclad.model.exception import RiskException
from tests.conftest import NOW, make_artifact, verdict_for


@pytest.fixture
def reg():
    return registry.discover()


class TestFindingContract:
    def test_a_bad_severity_is_a_hard_error(self) -> None:
        # A bad severity must never reach a client report.
        with pytest.raises(ValueError, match="bad severity"):
            Finding(module="m", target="CC6.1", severity="catastrophic", title="t")

    def test_a_valid_severity_is_accepted(self) -> None:
        finding = Finding(module="m", target="CC6.1", severity="high", title="t")
        assert finding.to_dict()["severity"] == "high"


class TestRegistry:
    def test_every_capability_declares_a_name_and_a_description(self, reg) -> None:
        for module in reg.values():
            assert module.name
            assert module.description

    def test_descriptions_never_name_an_underlying_tool(self, reg) -> None:
        # White-label rule: a client-facing surface never names a vendor tool.
        forbidden = ("zap", "nuclei", "wazuh", "prowler", "puppeteer", "openai", "gpt")
        for module in reg.values():
            lowered = module.description.lower()
            assert not any(name in lowered for name in forbidden), module.name

    def test_groups_run_from_narrow_to_broad(self, reg) -> None:
        quick = {m.name for m in registry.select(reg, group="quick")}
        standard = {m.name for m in registry.select(reg, group="standard")}
        deep = {m.name for m in registry.select(reg, group="deep")}
        assert quick < standard < deep

    def test_selecting_one_capability_pulls_its_prerequisites(self, reg) -> None:
        chosen = [m.name for m in registry.select(reg, modules=["remediation_plan"])]
        assert chosen.index("control_mapping") < chosen.index("remediation_plan")
        assert "evidence_inventory" in chosen

    def test_remediation_runs_after_exception_review(self, reg) -> None:
        # Otherwise the plan raises work for controls whose risk was accepted.
        chosen = [m.name for m in registry.select(reg, group="standard")]
        assert chosen.index("exception_review") < chosen.index("remediation_plan")

    def test_an_unknown_capability_names_what_is_available(self, reg) -> None:
        with pytest.raises(SelectionError, match="available:"):
            registry.select(reg, modules=["nonexistent"])

    def test_an_empty_group_is_refused(self, reg) -> None:
        with pytest.raises(SelectionError, match="no capabilities in group"):
            registry.select(reg, group="imaginary")

    def test_a_missing_prerequisite_is_refused(self) -> None:
        class Orphan(AssessmentModule):
            name = "orphan"
            description = "Requires something that is not registered."
            requires = ("absent",)

            def run(self, ctx):  # pragma: no cover - never reached
                return self.result([])

        with pytest.raises(SelectionError, match="not registered"):
            registry.order({"orphan": Orphan()}, [Orphan()])

    def test_a_dependency_cycle_is_refused(self) -> None:
        class Left(AssessmentModule):
            name = "left"
            description = "d"
            requires = ("right",)

            def run(self, ctx):  # pragma: no cover
                return self.result([])

        class Right(AssessmentModule):
            name = "right"
            description = "d"
            requires = ("left",)

            def run(self, ctx):  # pragma: no cover
                return self.result([])

        reg = {"left": Left(), "right": Right()}
        with pytest.raises(SelectionError, match="dependency cycle"):
            registry.order(reg, [reg["left"]])

    def test_the_catalog_matches_the_registry(self, reg) -> None:
        catalog = registry.catalog(reg)
        assert {entry["name"] for entry in catalog} == set(reg)


class TestRun:
    def test_corroborated_evidence_produces_a_pass(self, tiny_framework, evidence) -> None:
        result = run_assessment(
            tenant_id="acme",
            framework=tiny_framework,
            evidence=evidence,
            group="standard",
            as_of=NOW,
        )
        assert verdict_for(result, "CC6.1").status is ControlStatus.COMPLIANT

    def test_a_single_document_is_never_enough(self, tiny_framework) -> None:
        # One document is a claim; two is corroboration, which is the bar an
        # auditor applies.
        evidence = EvidenceSet(tenant_id="acme")
        evidence.add(
            make_artifact(
                "Access Control Policy",
                "Access control policy restricts logical access and registers authorized users.",
                evidence_type="Access control policy",
            )
        )
        result = run_assessment(
            tenant_id="acme",
            framework=tiny_framework,
            evidence=evidence,
            group="standard",
            as_of=NOW,
        )
        assert verdict_for(result, "CC6.1").status is ControlStatus.PARTIAL

    def test_unmatched_controls_report_as_gaps(self, tiny_framework, evidence) -> None:
        result = run_assessment(
            tenant_id="acme",
            framework=tiny_framework,
            evidence=evidence,
            group="standard",
            as_of=NOW,
        )
        assert verdict_for(result, "CC9.9").status is ControlStatus.GAP

    def test_expired_evidence_cannot_carry_a_control(self, tiny_framework, stale_evidence) -> None:
        result = run_assessment(
            tenant_id="acme",
            framework=tiny_framework,
            evidence=stale_evidence,
            group="standard",
            as_of=NOW,
        )
        verdict = verdict_for(result, "CC6.1")
        assert verdict.status is ControlStatus.PARTIAL
        assert "currency window" in verdict.rationale

    def test_an_empty_evidence_set_is_called_out_as_a_delivery_problem(
        self, tiny_framework
    ) -> None:
        result = run_assessment(
            tenant_id="acme",
            framework=tiny_framework,
            evidence=EvidenceSet(tenant_id="acme"),
            group="standard",
            as_of=NOW,
        )
        critical = [f for f in result.findings if f.severity == "critical"]
        assert any("No evidence was submitted" in f.title for f in critical)

    def test_an_operator_hint_produces_an_asserted_link(self, tiny_framework) -> None:
        evidence = EvidenceSet(tenant_id="acme")
        evidence.add(make_artifact("Scanned Policy", "", evidence_type="policy", hints=["CC9.9"]))
        result = run_assessment(
            tenant_id="acme",
            framework=tiny_framework,
            evidence=evidence,
            group="quick",
            as_of=NOW,
        )
        links = verdict_for(result, "CC9.9").evidence_links
        assert links and links[0].method is LinkMethod.MANUAL

    def test_evidence_from_another_tenant_is_refused(self, tiny_framework, evidence) -> None:
        # Assessing one client's evidence into another client's record is not a
        # warning condition.
        with pytest.raises(ValueError, match="belongs to tenant"):
            run_assessment(
                tenant_id="other-co",
                framework=tiny_framework,
                evidence=evidence,
                group="quick",
                as_of=NOW,
            )

    def test_the_run_is_recorded_in_the_audit_log(self, tiny_framework, evidence) -> None:
        result = run_assessment(
            tenant_id="acme",
            framework=tiny_framework,
            evidence=evidence,
            group="standard",
            as_of=NOW,
        )
        actions = {event.action for event in result.audit.events}
        assert {"assessment.started", "assessment.completed"} <= actions
        assert result.audit.is_valid()

    def test_the_same_inputs_produce_the_same_score(self, tiny_framework, evidence) -> None:
        scores = {
            run_assessment(
                tenant_id="acme",
                framework=tiny_framework,
                evidence=evidence,
                group="deep",
                as_of=NOW,
                assessment_id="fixed",
            ).assessment.summary.readiness_score
            for _ in range(3)
        }
        assert len(scores) == 1

    def test_a_capability_that_raises_does_not_lose_the_run(
        self, tiny_framework, evidence, monkeypatch
    ) -> None:
        from ironclad.modules.freshness_check import FreshnessCheck

        def explode(self, ctx):
            raise RuntimeError("simulated capability fault")

        monkeypatch.setattr(FreshnessCheck, "run", explode)
        result = run_assessment(
            tenant_id="acme",
            framework=tiny_framework,
            evidence=evidence,
            group="standard",
            as_of=NOW,
        )
        assert not result.ok
        assert "freshness_check" in result.failed_modules
        # The rest of the assessment still completed.
        assert verdict_for(result, "CC6.1").status is ControlStatus.COMPLIANT
        assert any("freshness_check" in w for w in result.warnings)


class TestExceptionsInARun:
    def _exception(self, expires_in_days: int = 90) -> RiskException:
        exception = RiskException(
            exception_id="ex-1",
            tenant_id="acme",
            control_id="CC9.9",
            justification="Compensating monitoring is in place until the next release.",
            requested_by="alice",
            requested_at=NOW,
            expires_at=NOW + timedelta(days=expires_in_days),
            compensating_controls=["Daily review of privileged activity"],
        )
        exception.submit()
        exception.approve("bob", at=NOW)
        return exception

    def test_an_active_acceptance_converts_a_gap(self, tiny_framework, evidence) -> None:
        result = run_assessment(
            tenant_id="acme",
            framework=tiny_framework,
            evidence=evidence,
            group="standard",
            exceptions=[self._exception()],
            as_of=NOW,
        )
        verdict = verdict_for(result, "CC9.9")
        assert verdict.status is ControlStatus.ACCEPTED_RISK
        assert verdict.exception_id == "ex-1"

    def test_a_lapsed_acceptance_reopens_the_gap(self, tiny_framework, evidence) -> None:
        result = run_assessment(
            tenant_id="acme",
            framework=tiny_framework,
            evidence=evidence,
            group="standard",
            exceptions=[self._exception(expires_in_days=10)],
            as_of=NOW + timedelta(days=30),
        )
        assert verdict_for(result, "CC9.9").status is ControlStatus.GAP
        assert any("has lapsed" in f.title for f in result.findings)

    def test_no_remediation_work_is_raised_for_an_accepted_risk(
        self, tiny_framework, evidence
    ) -> None:
        result = run_assessment(
            tenant_id="acme",
            framework=tiny_framework,
            evidence=evidence,
            group="standard",
            exceptions=[self._exception()],
            as_of=NOW,
        )
        assert "CC9.9" not in {item.control_id for item in result.plan.items}

    def test_an_imminent_expiry_is_flagged(self, tiny_framework, evidence) -> None:
        result = run_assessment(
            tenant_id="acme",
            framework=tiny_framework,
            evidence=evidence,
            group="standard",
            exceptions=[self._exception(expires_in_days=10)],
            as_of=NOW,
        )
        assert any("expires in" in f.title for f in result.findings)

    def test_an_acceptance_for_an_unknown_control_warns(self, tiny_framework, evidence) -> None:
        exception = self._exception()
        exception.control_id = "NOT-IN-FRAMEWORK"
        result = run_assessment(
            tenant_id="acme",
            framework=tiny_framework,
            evidence=evidence,
            group="standard",
            exceptions=[exception],
            as_of=NOW,
        )
        assert any("NOT-IN-FRAMEWORK" in w for w in result.warnings)


class TestConsensusPayload:
    def test_findings_are_base64_encoded_for_the_ai_engine(self, tiny_framework, evidence) -> None:
        # The consensus engine's findings_json input is base64. Raw JSON there
        # produces an analysis over nothing.
        import base64
        import json

        result = run_assessment(
            tenant_id="acme",
            framework=tiny_framework,
            evidence=evidence,
            group="standard",
            as_of=NOW,
        )
        decoded = json.loads(base64.b64decode(result.consensus_payload()))
        assert decoded == result.findings_payload()

    def test_a_valid_consensus_is_folded_in(self, tiny_framework, evidence) -> None:
        import base64
        import json

        result = run_assessment(
            tenant_id="acme",
            framework=tiny_framework,
            evidence=evidence,
            group="quick",
            as_of=NOW,
        )
        payload = base64.b64encode(
            json.dumps({"severity": "HIGH", "confidence": 80}).encode()
        ).decode()
        merged = merge_consensus(result, payload)
        assert merged["severity"] == "HIGH"
        assert merged["status"] == "ok"

    def test_an_empty_consensus_is_recorded_as_unavailable(self, tiny_framework, evidence) -> None:
        # The engine documents an empty output when analysis fails. The
        # assessment must still be storable and reportable.
        result = run_assessment(
            tenant_id="acme",
            framework=tiny_framework,
            evidence=evidence,
            group="quick",
            as_of=NOW,
        )
        assert merge_consensus(result, "")["status"] == "unavailable"

    def test_an_undecodable_consensus_does_not_lose_the_assessment(
        self, tiny_framework, evidence
    ) -> None:
        result = run_assessment(
            tenant_id="acme",
            framework=tiny_framework,
            evidence=evidence,
            group="quick",
            as_of=NOW,
        )
        assert merge_consensus(result, "!!not base64!!")["status"] == "undecodable"
        assert result.assessment.summary.total_controls == 3

    def test_an_unexpected_consensus_shape_is_rejected(self, tiny_framework, evidence) -> None:
        import base64
        import json

        result = run_assessment(
            tenant_id="acme",
            framework=tiny_framework,
            evidence=evidence,
            group="quick",
            as_of=NOW,
        )
        payload = base64.b64encode(json.dumps(["not", "an", "object"]).encode()).decode()
        assert merge_consensus(result, payload)["status"] == "unexpected_shape"


class TestModuleContext:
    def test_a_module_can_contribute_output_and_warnings(self, tiny_framework) -> None:
        class Probe(AssessmentModule):
            name = "probe"
            description = "Test capability."
            groups = ("probe",)

            def run(self, ctx: AssessmentContext) -> ModuleResult:
                ctx.warn("a warning")
                ctx.warn("a warning")  # deduplicated
                ctx.module_output[self.name] = {"ran": True}
                return self.result([], ran=True)

        ctx = AssessmentContext(
            tenant_id="acme",
            framework=Framework(id="f", name="F", version="1"),
            evidence=EvidenceSet(tenant_id="acme"),
            assessment=None,  # type: ignore[arg-type]
            audit=None,  # type: ignore[arg-type]
        )
        Probe().run(ctx)
        assert ctx.warnings == ["a warning"]
        assert ctx.module_output["probe"] == {"ran": True}


class TestCrosswalkProjection:
    """The projection path against the real shipped frameworks and crosswalks."""

    def _run(self, framework_dir):
        from ironclad.frameworks.crosswalk import load_crosswalks
        from ironclad.frameworks.loader import load_framework

        evidence = EvidenceSet(tenant_id="acme")
        evidence.add(
            make_artifact(
                "Information Security Policy",
                "Access control policy: least privilege, role definitions, separation of "
                "duties, user access review, privileged access register. Encryption "
                "standard, key management procedures, TLS configuration. Incident response "
                "plan, containment, root cause analysis. Backup policy, restore test "
                "records, disaster recovery plan. Vendor risk management policy and vendor "
                "inventory. Security awareness training records. Change management, change "
                "tickets, configuration baselines, hardening standards. Logging standard, "
                "log retention configuration, log review records.",
                evidence_type="Information security policy",
            )
        )
        evidence.add(
            make_artifact(
                "Access Review and Risk Assessment",
                "User access review, permission export, reviewer approvals, role "
                "definitions, least privilege. Risk assessment, risk register, risk "
                "scoring methodology, threat model, vulnerability scan reports, "
                "remediation tracker, business impact analysis. Board charter, meeting "
                "minutes, org chart, job descriptions, RACI matrix.",
                evidence_type="User access review",
            )
        )
        return run_assessment(
            tenant_id="acme",
            framework=load_framework("soc2", framework_dir),
            evidence=evidence,
            group="deep",
            crosswalk=load_crosswalks(framework_dir / "crosswalks"),
            as_of=NOW,
            framework_dir=framework_dir,
        )

    def test_verdicts_project_onto_the_other_frameworks(self, framework_dir) -> None:
        result = self._run(framework_dir)
        projections = result.module_output["crosswalk_coverage"]["projections"]
        assert set(projections) == {"nist-csf", "pci-dss", "hipaa"}

    def test_a_projection_never_includes_the_source_framework(self, framework_dir) -> None:
        result = self._run(framework_dir)
        assert "soc2-tsc" not in result.module_output["crosswalk_coverage"]["projections"]

    def test_a_projection_reports_what_still_needs_direct_review(self, framework_dir) -> None:
        result = self._run(framework_dir)
        hipaa = result.module_output["crosswalk_coverage"]["projections"]["hipaa"]
        assert hipaa["mapped_share"] > 0.5
        # An honest projection names the controls it cannot speak to.
        assert isinstance(hipaa["unmapped_controls"], list)

    def test_every_projected_verdict_names_its_source(self, framework_dir) -> None:
        result = self._run(framework_dir)
        for projection in result.module_output["crosswalk_coverage"]["projections"].values():
            for verdict in projection["verdicts"].values():
                assert verdict["inherited_from"].startswith("soc2-tsc:")

    def test_the_projection_findings_are_informational(self, framework_dir) -> None:
        # A projection is not a finding against the tenant.
        result = self._run(framework_dir)
        projection_findings = [f for f in result.findings if f.module == "crosswalk_coverage"]
        assert projection_findings
        assert all(f.severity == "info" for f in projection_findings)

    def test_no_crosswalks_degrades_with_a_warning(self, framework_dir) -> None:
        from ironclad.frameworks.crosswalk import Crosswalk
        from ironclad.frameworks.loader import load_framework

        result = run_assessment(
            tenant_id="acme",
            framework=load_framework("soc2", framework_dir),
            evidence=EvidenceSet(tenant_id="acme"),
            group="deep",
            crosswalk=Crosswalk(),
            as_of=NOW,
            framework_dir=framework_dir,
        )
        assert result.ok
        assert any("cross-framework" in w for w in result.warnings)
