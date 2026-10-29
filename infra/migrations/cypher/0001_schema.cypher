// Knowledge graph schema: unique key constraint per node label
// (mirrors NODE_KEY_PROPERTY in gg_ingestion.extract.model) plus the
// doc_type lookup index used by traversal tools.

CREATE CONSTRAINT document_key IF NOT EXISTS
FOR (n:Document) REQUIRE n.doc_key IS UNIQUE;

CREATE CONSTRAINT document_revision_key IF NOT EXISTS
FOR (n:DocumentRevision) REQUIRE n.key IS UNIQUE;

CREATE CONSTRAINT requirement_key IF NOT EXISTS
FOR (n:Requirement) REQUIRE n.req_id IS UNIQUE;

CREATE CONSTRAINT design_output_key IF NOT EXISTS
FOR (n:DesignOutput) REQUIRE n.do_id IS UNIQUE;

CREATE CONSTRAINT supplier_key IF NOT EXISTS
FOR (n:Supplier) REQUIRE n.supplier_id IS UNIQUE;

CREATE CONSTRAINT person_key IF NOT EXISTS
FOR (n:Person) REQUIRE n.name IS UNIQUE;

CREATE CONSTRAINT fmea_row_key IF NOT EXISTS
FOR (n:FmeaRow) REQUIRE n.key IS UNIQUE;

CREATE CONSTRAINT schema_migration_name IF NOT EXISTS
FOR (n:SchemaMigration) REQUIRE n.name IS UNIQUE;

CREATE INDEX document_doc_type IF NOT EXISTS
FOR (n:Document) ON (n.doc_type);
