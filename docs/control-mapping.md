# Cross-framework control mapping

**Generated from `frameworks/crosswalks/*.json` — do not edit by hand.**
Regenerate with `python tools/build_control_mapping.py`.

SOC 2 Trust Service Criteria is the hub. A client evidences a control once against it and the
engine projects that verdict onto the other frameworks, so the same
access-control policy is not requested three times over.

## What a relationship means

The direction is recorded, not assumed, because getting it backwards would let
a narrow control claim to cover a broad one.

| Relationship | Meaning | Carries a verdict |
|---|---|---|
| `equivalent` | the same requirement in different words | yes, at 0.9 confidence |
| `superset` | the source is broader; satisfying it covers the target | yes, at 0.8 confidence |
| `subset` | the source is narrower; satisfying it is not enough | only ever a partial, at 0.5 |
| `related` | a pointer for a human | **never** |

A projected verdict can never be better than the verdict it came from, and is
always labelled as inherited, naming the control it came from. Nothing
projected is presented as directly evidenced.

An accepted risk never travels: a risk one board signed for under one framework
is not an answer to a different framework's auditor.

## Coverage

| Target framework | Controls | Addressed by a SOC 2 assessment | Needs direct review |
|---|---|---|---|
| NIST CSF 2.0 | 43 | 67% | 14 |
| PCI DSS 4.0 | 27 | 82% | 5 |
| HIPAA Security Rule | 23 | 96% | 1 |

## SOC 2 → NIST CSF 2.0

| SOC 2 | Criterion | Maps to | Relationship | Note |
|---|---|---|---|---|
| `CC1.1` | Integrity and Ethical Values | `GV.PO-01` | subset | Code of conduct is one part of the cybersecurity policy set. |
| `CC1.1` | Integrity and Ethical Values | `GV.RR-01` | equivalent | Tone at the top and leadership accountability. |
| `CC1.2` | Board Independence | `GV.RR-01` | subset | Board oversight is one facet of leadership accountability. |
| `CC1.3` | Organizational Structure | `GV.RR-02` | equivalent | Structures, reporting lines and authorities. |
| `CC1.4` | Competence Commitment | `PR.AT-01` | subset | Competence includes but exceeds awareness training. |
| `CC1.5` | Accountability | `GV.RR-02` | subset | Accountability enforcement within roles and responsibilities. |
| `CC2.1` | Information Quality | `ID.AM-05` | related | Information quality supports asset classification. |
| `CC2.2` | Internal Communication | `GV.PO-01` | subset | Internal communication of policy. |
| `CC2.2` | Internal Communication | `PR.AT-01` | subset | Communicating responsibilities to personnel. |
| `CC2.3` | External Communication | `GV.OC-02` | equivalent | External communication with stakeholders. |
| `CC3.1` | Risk Objectives | `GV.RM-01` | equivalent | Objectives specified to enable risk identification. |
| `CC3.2` | Risk Identification | `ID.RA-01` | subset | Vulnerability identification is part of risk analysis. |
| `CC3.2` | Risk Identification | `ID.RA-05` | equivalent | Risk identification and analysis. |
| `CC3.3` | Fraud Risk | `ID.RA-03` | equivalent | Consideration of fraud and threat sources. |
| `CC3.4` | Change Assessment | `ID.IM-01` | equivalent | Identifying and assessing changes, feeding improvement. |
| `CC4.1` | Control Evaluation | `ID.IM-01` | equivalent | Ongoing and separate evaluations. |
| `CC4.2` | Deficiency Communication | `RS.CO-02` | subset | Communicating deficiencies to responsible parties. |
| `CC5.1` | Control Activities | `GV.PO-01` | subset | Control activities selected to mitigate risk. |
| `CC5.2` | Technology Controls | `PR.PS-01` | subset | Technology general controls include configuration management. |
| `CC5.3` | Policy Deployment | `GV.PO-02` | equivalent | Control activities deployed through policy and procedure. |
| `CC6.1` | Logical and Physical Access | `PR.AA-05` | equivalent | Logical access security over protected assets. |
| `CC6.1` | Logical and Physical Access | `PR.DS-01` | subset | Encryption at rest is one logical access measure. |
| `CC6.2` | Access Provisioning | `PR.AA-01` | equivalent | Registration and authorization of users. |
| `CC6.3` | Role-Based Access | `PR.AA-05` | equivalent | Access is modified and removed based on roles. |
| `CC6.4` | Physical Access | `PR.AA-06` | equivalent | Physical access to facilities and protected assets. |
| `CC6.5` | Asset Disposal | `PR.DS-01` | subset | Protecting data on decommissioned assets. |
| `CC6.6` | External Threat Protection | `PR.IR-01` | equivalent | Protection against threats from outside the boundary. |
| `CC6.7` | Data Transmission Protection | `PR.DS-02` | equivalent | Restricting transmission, movement and removal of data. |
| `CC6.8` | Malware Prevention | `DE.CM-09` | equivalent | Detecting and preventing unauthorized software. |
| `CC7.1` | Security Event Detection | `DE.CM-09` | equivalent | Detection of configuration change and vulnerabilities. |
| `CC7.1` | Security Event Detection | `ID.RA-01` | subset | Vulnerability identification feeds detection. |
| `CC7.2` | Security Event Monitoring | `DE.CM-01` | equivalent | Monitoring for anomalies and adverse events. |
| `CC7.3` | Security Event Evaluation | `DE.AE-02` | equivalent | Evaluating events to determine whether they are incidents. |
| `CC7.4` | Incident Response | `RS.MA-01` | equivalent | Responding to identified security incidents. |
| `CC7.4` | Incident Response | `RS.MI-01` | subset | Containment is one part of incident response. |
| `CC7.5` | Incident Recovery | `RC.RP-01` | equivalent | Recovery from identified security incidents. |
| `CC8.1` | Change Management | `PR.PS-01` | equivalent | Change management over infrastructure and software. |
| `CC8.1` | Change Management | `PR.PS-02` | subset | Software maintenance is part of change management. |
| `CC9.1` | Risk Mitigation | `RC.RP-01` | subset | Business disruption risk mitigation includes recovery. |
| `CC9.2` | Vendor Risk Management | `GV.SC-01` | equivalent | Vendor and business partner risk management. |
| `CC9.2` | Vendor Risk Management | `GV.SC-04` | subset | Supplier prioritization is part of vendor risk management. |

**No SOC 2 mapping (14):** `DE.AE-06`, `DE.CM-03`, `GV.OC-01`, `GV.OC-03`, `GV.RM-02`, `ID.AM-01`, `ID.AM-02`, `PR.AA-03`, `PR.DS-11`, `PR.PS-04`, `RC.CO-03`, `RC.RP-05`, `RS.AN-03`, `RS.MA-02`. These require a direct assessment against NIST CSF 2.0.

## SOC 2 → PCI DSS 4.0

| SOC 2 | Criterion | Maps to | Relationship | Note |
|---|---|---|---|---|
| `CC1.5` | Accountability | `12.1` | subset | Accountability is asserted through the security policy. |
| `CC2.2` | Internal Communication | `12.6` | subset | Communicating security responsibilities via awareness education. |
| `CC3.2` | Risk Identification | `11.3` | subset | Vulnerability scanning supports risk identification. |
| `CC3.2` | Risk Identification | `6.3` | subset | Risk analysis includes vulnerability ranking. |
| `CC4.1` | Control Evaluation | `11.4` | subset | Penetration testing is one form of separate evaluation. |
| `CC5.3` | Policy Deployment | `12.1` | equivalent | Policies and procedures deploying control activities. |
| `CC6.1` | Logical and Physical Access | `3.5` | subset | Rendering stored account data unreadable. |
| `CC6.1` | Logical and Physical Access | `7.2` | equivalent | Access defined and assigned by need to know. |
| `CC6.1` | Logical and Physical Access | `7.3` | equivalent | Access enforced by an access control system. |
| `CC6.2` | Access Provisioning | `8.2` | equivalent | Unique user identification and account management. |
| `CC6.2` | Access Provisioning | `8.3` | subset | Strong authentication supports registration and authorization. |
| `CC6.2` | Access Provisioning | `8.4` | subset | Multi-factor authentication for CDE and remote access. |
| `CC6.3` | Role-Based Access | `8.2` | subset | Account removal on termination. |
| `CC6.4` | Physical Access | `9.4` | related | Physical access and media protection. |
| `CC6.5` | Asset Disposal | `9.4` | equivalent | Secure disposal of media holding account data. |
| `CC6.6` | External Threat Protection | `1.2` | equivalent | Network security control configuration. |
| `CC6.6` | External Threat Protection | `1.3` | equivalent | Restricting access to and from the cardholder data environment. |
| `CC6.7` | Data Transmission Protection | `4.2` | equivalent | Protecting account data in transit. |
| `CC6.8` | Malware Prevention | `2.2` | subset | Only necessary services and secure configuration. |
| `CC6.8` | Malware Prevention | `5.2` | equivalent | Preventing and detecting malicious software. |
| `CC7.1` | Security Event Detection | `11.3` | equivalent | Regular identification of vulnerabilities. |
| `CC7.1` | Security Event Detection | `2.2` | subset | Configuration standards detect deviation. |
| `CC7.2` | Security Event Monitoring | `10.2` | equivalent | Audit logs supporting anomaly detection. |
| `CC7.2` | Security Event Monitoring | `10.4` | equivalent | Reviewing logs to identify suspicious activity. |
| `CC7.3` | Security Event Evaluation | `10.4` | subset | Log review evaluates events for incident status. |
| `CC7.4` | Incident Response | `12.10` | equivalent | Incident response readiness and execution. |
| `CC8.1` | Change Management | `6.2` | subset | Secure development is part of change management. |
| `CC8.1` | Change Management | `6.3` | subset | Patching is part of change management. |
| `CC9.2` | Vendor Risk Management | `12.8` | equivalent | Third-party service provider risk management. |

**No SOC 2 mapping (5):** `1.1`, `10.3`, `2.3`, `3.3`, `6.4`. These require a direct assessment against PCI DSS 4.0.

## SOC 2 → HIPAA Security Rule

| SOC 2 | Criterion | Maps to | Relationship | Note |
|---|---|---|---|---|
| `CC1.3` | Organizational Structure | `164.308(a)(3)(ii)(A)` | related | Structures and authorization of workforce. |
| `CC1.4` | Competence Commitment | `164.308(a)(5)(ii)(B)` | related | Workforce competence and awareness. |
| `CC3.2` | Risk Identification | `164.308(a)(1)(ii)(A)` | equivalent | Risk analysis over ePHI. |
| `CC3.2` | Risk Identification | `164.308(a)(1)(ii)(B)` | subset | Risk identification feeds risk management. |
| `CC4.1` | Control Evaluation | `164.308(a)(8)` | equivalent | Periodic evaluation of safeguards. |
| `CC5.3` | Policy Deployment | `164.316(a)` | equivalent | Policies and procedures implementing the standards. |
| `CC6.1` | Logical and Physical Access | `164.312(a)(1)` | equivalent | Technical access control over ePHI. |
| `CC6.2` | Access Provisioning | `164.308(a)(4)(ii)(B)` | equivalent | Granting access based on authorization. |
| `CC6.2` | Access Provisioning | `164.312(d)` | subset | Authentication of the person seeking access. |
| `CC6.3` | Role-Based Access | `164.308(a)(3)(ii)(C)` | subset | Termination removes access. |
| `CC6.3` | Role-Based Access | `164.308(a)(4)(ii)(C)` | equivalent | Establishing, reviewing and modifying access. |
| `CC6.4` | Physical Access | `164.310(a)(1)` | equivalent | Facility access controls. |
| `CC6.5` | Asset Disposal | `164.310(d)(2)(i)` | equivalent | Disposal of media holding ePHI. |
| `CC6.6` | External Threat Protection | `164.312(e)(1)` | subset | Boundary protection supports transmission security. |
| `CC6.7` | Data Transmission Protection | `164.312(e)(1)` | equivalent | Transmission security over open networks. |
| `CC6.8` | Malware Prevention | `164.308(a)(5)(ii)(B)` | equivalent | Guarding against malicious software. |
| `CC7.1` | Security Event Detection | `164.312(c)(1)` | subset | Integrity monitoring detects improper alteration. |
| `CC7.2` | Security Event Monitoring | `164.308(a)(1)(ii)(D)` | equivalent | Information system activity review. |
| `CC7.2` | Security Event Monitoring | `164.308(a)(5)(ii)(C)` | subset | Log-in monitoring is one monitored activity. |
| `CC7.2` | Security Event Monitoring | `164.312(b)` | equivalent | Audit controls recording and examining activity. |
| `CC7.4` | Incident Response | `164.308(a)(6)(ii)` | equivalent | Security incident response and reporting. |
| `CC7.5` | Incident Recovery | `164.308(a)(7)(ii)(B)` | equivalent | Recovery and restoration of lost data. |
| `CC9.1` | Risk Mitigation | `164.308(a)(7)(ii)(A)` | subset | Backup plan supports business disruption mitigation. |
| `CC9.2` | Vendor Risk Management | `164.308(b)(1)` | equivalent | Business associate assurances. |

**No SOC 2 mapping (1):** `164.316(b)(2)(i)`. These require a direct assessment against HIPAA Security Rule.
