# Local XSD validation

No official ISO 20022 XSD files are bundled in this first release. The validator uses an XSD only if a matching local file exists here; it will never download schemas. Before adding XSDs, review and comply with the applicable license and redistribution terms. Keep the schema version aligned with `app/formats.py` and add regression tests for the version before enabling it in a release.
