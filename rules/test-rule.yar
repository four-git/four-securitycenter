/* Harmless validation rule; NOT real malware coverage. */
rule four_securitycenter_benign_test
{
    meta:
        description = "Match a deliberately harmless four-securitycenter test string"
        author = "four-securitycenter"
    strings:
        $marker = "FOUR_SECURITYCENTER_YARA_TEST_SAMPLE" ascii
    condition:
        $marker
}
