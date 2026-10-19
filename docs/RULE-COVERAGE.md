# Large-media rule coverage

The initial YARA test rule only proves the engine works. It is not a malware rule.

`media-payload-indicators.yar` adds two locally reviewed triage rules:

1. An embedded DOS/PE header with internally consistent executable signature, in an MKV/MP4 container.
2. Several script execution/encoded payload strings in combination, in an MKV/MP4 container.

Neither rule limits filesize or requires payload patterns near the beginning of the file. They do not execute embedded data. Rules are versioned with the repository and their exact SHA256 is recorded with results. Rule matches must be labelled YARA_MATCH / review, never automatically confirmed malware.

Coverage is NARROW: these detect selected suspicious payload shapes, not all malware, codec vulnerabilities, archives, obfuscation or every possible container. Legitimate media about security may contain these strings; executable attachments can also be intentional. No match means these rules did not match, NOT a guarantee that a large file is safe. Files outside MKV/MP4 are not covered by these two rules. Container-header checks are heuristics, not complete structural validation.

ClamAV's per-file ceiling remains independent. A large file checked only by these rules must be PARTIALLY_SCANNED, with ClamAV SKIPPED_SIZE_LIMIT. This is not antivirus-equivalent coverage and no file should receive an unqualified safe verdict.

The prior native Pi validation exercised both media triage rules beyond byte2,200,000,000 and confirmed the benign fixture produced no match. See [recorded results and Docker acceptance checks](DOCKER-RUNBOOK.md#prior-native-validation). Repeat validation and resource checks in containers before enabling automatic scanning.

A broad maintained malware rule pack or another AV engine can be evaluated separately; none has been silently enabled. Downloaded signature-base repository was inspected as a possible source but is not deployed.
