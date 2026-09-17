"""Registry selection, capability behaviour, and the orchestrated run."""

from __future__ import annotations

from datetime import timedelta

import pytest

from ironclad import registry
from ironclad.base import AssessmentContext, AssessmentModule, Finding, ModuleResult
from ironclad.engine import (
    CONSENSUS_MAX_FINDINGS,
    consensus_findings,
    merge_consensus,
    run_assessment,
)
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

    def test_asserted_links_to_unread_items_cannot_make_a_control_compliant(
        self, tiny_framework
    ) -> None:
        # Two remote URIs nobody read, each hinting every control, scored 100%
        # readiness. An assertion supports a control; on its own it does not
        # evidence it.
        ids = [c.id for c in tiny_framework.controls]
        evidence = EvidenceSet(tenant_id="acme")
        evidence.add(make_artifact("Everything A", "", evidence_type="policy", hints=ids))
        evidence.add(make_artifact("Everything B", "", evidence_type="access review", hints=ids))
        result = run_assessment(
            tenant_id="acme", framework=tiny_framework, evidence=evidence, group="quick", as_of=NOW
        )
        statuses = {v.status for v in result.assessment.controls}
        assert statuses == {ControlStatus.PARTIAL}
        assert "by assertion only" in verdict_for(result, ids[0]).rationale
        assert any("rest on asserted links" in w for w in result.warnings)
        held = result.module_output["control_mapping"]["asserted_only"]
        # CC9.9 has no points of focus and never reached compliant to begin with
        assert set(held) == {"CC6.1", "CC1.1"}

    def test_an_asserted_scanned_policy_beside_a_readable_item_still_counts(
        self, tiny_framework, evidence
    ) -> None:
        # The case the assertion exists for: a scanned policy the engine cannot
        # read, beside evidence it can. The assertion is not thrown away.
        evidence.add(make_artifact("Scanned Policy", "", evidence_type="policy", hints=["CC6.1"]))
        result = run_assessment(
            tenant_id="acme", framework=tiny_framework, evidence=evidence, group="quick", as_of=NOW
        )
        verdict = verdict_for(result, "CC6.1")
        methods = {link.method for link in verdict.evidence_links}
        assert LinkMethod.MANUAL in methods and LinkMethod.AUTOMATED in methods
        assert "by assertion only" not in verdict.rationale
        assert result.module_output["control_mapping"]["asserted_only"] == []

    def test_a_document_that_is_the_framework_is_named_not_believed(self) -> None:
        # Two files holding every SOC 2 control's own description scored 100%.
        # Matching is on words and the engine cannot tell a policy that quotes
        # the criteria from a copy of them, so it names both signals for the
        # analyst rather than pretending to a judgement.
        from ironclad.frameworks.loader import load_framework

        framework = load_framework("soc2")
        text = " ".join(
            f"{c.name}. {c.description} " + " ".join(p.description for p in c.points_of_focus)
            for c in framework.controls
        )
        evidence = EvidenceSet(tenant_id="acme")
        evidence.add(make_artifact("security-policy.txt", text, evidence_type="policy"))
        evidence.add(
            make_artifact("access-review.txt", text + " Reviewed.", evidence_type="access review")
        )
        result = run_assessment(
            tenant_id="acme", framework=framework, evidence=evidence, group="quick", as_of=NOW
        )
        output = result.module_output["control_mapping"]
        assert {b["name"] for b in output["implausibly_broad"]} == {
            "security-policy.txt",
            "access-review.txt",
        }
        assert all(q["controls"] == len(framework.controls) for q in output["quotes_framework"])
        assert sum("rarely evidences most of a framework" in w for w in result.warnings) == 2
        assert sum("framework's own wording" in w for w in result.warnings) == 2

    def test_ordinary_evidence_raises_neither_signal(self, evidence) -> None:
        from ironclad.frameworks.loader import load_framework

        result = run_assessment(
            tenant_id="acme",
            framework=load_framework("soc2"),
            evidence=evidence,
            group="quick",
            as_of=NOW,
        )
        output = result.module_output["control_mapping"]
        assert output["implausibly_broad"] == [] and output["quotes_framework"] == []

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


def _engine_result(severity: str = "High", confidence: float = 82.5, successful: int = 12) -> dict:
    """One ConsensusResult as `consensus-engine/src/consensus_engine.py` emits it.

    The field names are the engine's dataclass, read from the source rather
    than assumed: the first merge read `severity` and `confidence`, which the
    engine has never produced.
    """
    return {
        "consensus_severity": severity,
        "confidence_percent": confidence,
        "exploitability": "Medium",
        "impact": "High",
        "false_positive_likelihood": "Low",
        "internet_exposed": False,
        "compliance_impact": {"audit_risk": "High"},
        "aggregated_remediation": ["Adopt a second evidence source", "Document the review"],
        "verification_steps": ["Request the artefact"],
        "total_models": 15,
        "successful_models": successful,
        "failed_models": 15 - successful,
        "severity_distribution": {"High": successful},
        "weighted_scores": {},
        "model_responses": [],
        "engine_version": "5.0",
        "timestamp": "2026-09-12T22:00:00Z",
    }


def _b64(payload: object) -> str:
    import base64
    import json

    return base64.b64encode(json.dumps(payload).encode()).decode()


class TestConsensusPayload:
    def _run(self, tiny_framework, evidence, group: str = "standard"):
        return run_assessment(
            tenant_id="acme",
            framework=tiny_framework,
            evidence=evidence,
            group=group,
            as_of=NOW,
        )

    def test_findings_are_base64_encoded_for_the_ai_engine(self, tiny_framework, evidence) -> None:
        # The consensus engine's findings_json input is base64. Raw JSON there
        # produces an analysis over nothing.
        import base64
        import json

        result = self._run(tiny_framework, evidence)
        decoded = json.loads(base64.b64decode(result.consensus_payload()))
        assert decoded == consensus_findings(result.findings_payload())
        assert decoded, "the sample evidence leaves gaps, so something is sent"

    def test_the_payload_is_one_item_per_control_and_never_info(
        self, tiny_framework, evidence
    ) -> None:
        # The control mapping and the remediation plan each raise a finding for
        # the same gap; the engine queries fifteen models per item, so sending
        # both analysed every gap twice. Coverage notes are `info` and have no
        # severity to triage.
        result = self._run(tiny_framework, evidence, group="deep")
        everything = result.findings_payload()
        sent = consensus_findings(everything)
        targets = [f["target"] for f in sent]
        assert len(targets) == len(set(targets))
        assert all(f["severity"] != "info" for f in sent)
        assert len(sent) < len(everything)
        assert {f["target"] for f in sent} == {
            f["target"] for f in everything if f["severity"] != "info"
        }

    def test_the_payload_is_most_severe_first_and_capped(self) -> None:
        findings = [
            {"module": "m", "target": f"C{i}", "severity": "medium", "title": f"C{i}"}
            for i in range(40)
        ] + [{"module": "m", "target": "HOT", "severity": "critical", "title": "HOT"}]
        sent = consensus_findings(findings)
        assert len(sent) == CONSENSUS_MAX_FINDINGS
        assert sent[0]["target"] == "HOT"

    def test_the_higher_severity_wins_when_a_control_has_two_findings(self) -> None:
        findings = [
            {"module": "a", "target": "C1", "severity": "medium", "title": "first"},
            {"module": "b", "target": "C1", "severity": "high", "title": "second"},
        ]
        sent = consensus_findings(findings)
        assert [f["title"] for f in sent] == ["second"]

    def test_a_list_of_engine_results_is_folded_in_by_position(
        self, tiny_framework, evidence
    ) -> None:
        # The engine returns a JSON list, one ConsensusResult per finding, and
        # nothing in a result names its finding. The first merge treated a
        # list as an unexpected shape, so every real assessment — which sends
        # more than one finding — discarded its analysis.
        result = self._run(tiny_framework, evidence)
        sent = consensus_findings(result.findings_payload())
        assert len(sent) >= 2
        answers = [_engine_result("High", 90.0)] + [
            _engine_result("Medium", 70.0) for _ in sent[1:]
        ]
        merged = merge_consensus(result, _b64(answers))
        assert merged["status"] == "ok"
        assert merged["analysed"] == len(sent) == merged["sent"]
        assert merged["severity"] == "high"
        assert merged["results"][0]["target"] == sent[0]["target"]
        assert merged["results"][0]["severity"] == "high"
        assert merged["results"][0]["confidence"] == 90.0
        assert merged["results"][0]["remediation"][0] == "Adopt a second evidence source"
        assert merged["results"][1]["severity"] == "medium"
        expected_mean = round((90.0 + 70.0 * (len(sent) - 1)) / len(sent), 1)
        assert merged["confidence"] == expected_mean
        assert merged["models_responded"] == 12 * len(sent)
        assert "most significant gap" in merged["summary"]
        assert result.assessment.consensus is merged
        assert any(e.action == "assessment.consensus_merged" for e in result.audit.events)
        assert not result.warnings

    def test_a_single_object_is_one_result(self, tiny_framework, evidence) -> None:
        # With exactly one finding the engine emits the object itself, not a
        # one-element list.
        result = self._run(tiny_framework, evidence)
        merged = merge_consensus(result, _b64(_engine_result("Critical", 95.0)))
        assert merged["status"] == "ok"
        assert merged["analysed"] == 1
        assert merged["severity"] == "critical"
        sent = consensus_findings(result.findings_payload())
        if len(sent) > 1:
            assert any("matched by position" in w for w in result.warnings)

    def test_a_count_mismatch_is_reported_not_hidden(self, tiny_framework, evidence) -> None:
        result = self._run(tiny_framework, evidence)
        sent = consensus_findings(result.findings_payload())
        merged = merge_consensus(result, _b64([_engine_result()] * (len(sent) + 3)))
        assert merged["analysed"] == len(sent)
        assert any(
            f"returned {len(sent) + 3} result(s) for {len(sent)}" in w for w in result.warnings
        )

    def test_no_model_responding_is_not_commentary(self, tiny_framework, evidence) -> None:
        result = self._run(tiny_framework, evidence)
        sent = consensus_findings(result.findings_payload())
        answers = [_engine_result("Medium", 0.0, successful=0) for _ in sent]
        merged = merge_consensus(result, _b64(answers))
        assert merged["status"] == "no_models"
        assert any("no model responded" in w for w in result.warnings)

    def test_the_stored_result_merges_identically_to_the_live_one(
        self, tiny_framework, evidence
    ) -> None:
        # The report job rebuilds the result from assessment.json and merges
        # there. Same findings, same subset, same alignment.
        import json

        from ironclad.cli import _StoredResult

        live = self._run(tiny_framework, evidence)
        stored = _StoredResult(json.loads(json.dumps(live.to_dict())))
        sent = consensus_findings(live.findings_payload())
        answers = [_engine_result("High", 80.0) for _ in sent]
        a = merge_consensus(live, _b64(answers))
        b = merge_consensus(stored, _b64(answers))
        assert a["results"] == b["results"]
        assert a["severity"] == b["severity"] and a["confidence"] == b["confidence"]

    def test_an_empty_consensus_is_recorded_as_unavailable(self, tiny_framework, evidence) -> None:
        # The engine documents an empty output when analysis fails. The
        # assessment must still be storable and reportable.
        result = self._run(tiny_framework, evidence, group="quick")
        assert merge_consensus(result, "")["status"] == "unavailable"

    def test_an_undecodable_consensus_does_not_lose_the_assessment(
        self, tiny_framework, evidence
    ) -> None:
        result = self._run(tiny_framework, evidence, group="quick")
        assert merge_consensus(result, "!!not base64!!")["status"] == "undecodable"
        assert result.assessment.summary.total_controls == 3

    def test_an_unexpected_consensus_shape_is_rejected(self, tiny_framework, evidence) -> None:
        result = self._run(tiny_framework, evidence, group="quick")
        assert merge_consensus(result, _b64(["not", "objects"]))["status"] == "unexpected_shape"
        assert merge_consensus(result, _b64("a string"))["status"] == "unexpected_shape"


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
