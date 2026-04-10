## ADDED Requirements

### Requirement: SnapshotStore interface abstracts storage backend

The `SnapshotStore` interface SHALL define three methods: `store(sessionId, html)` returning the snapshot URL, `delete(sessionId)` removing the snapshot, and `exists(sessionId)` checking existence. Two implementations SHALL be provided: `LocalSnapshotStore` for development and `S3SnapshotStore` for production.

#### Scenario: Store method returns URL

- **GIVEN** a `SnapshotStore` implementation
- **WHEN** `store("abc-123", "<html>...</html>")` is called
- **THEN** the snapshot is persisted
- **AND** a URL string is returned

#### Scenario: Delete method removes snapshot

- **GIVEN** a stored snapshot for session `abc-123`
- **WHEN** `delete("abc-123")` is called
- **THEN** the snapshot is removed from storage
- **AND** subsequent calls to `exists("abc-123")` return `false`

#### Scenario: Exists method checks presence

- **GIVEN** a stored snapshot for session `abc-123`
- **WHEN** `exists("abc-123")` is called
- **THEN** `true` is returned

- **GIVEN** no snapshot for session `xyz-999`
- **WHEN** `exists("xyz-999")` is called
- **THEN** `false` is returned

### Requirement: LocalSnapshotStore writes to filesystem

The `LocalSnapshotStore` SHALL write HTML files to `data/snapshots/{sessionId}.html` on the local filesystem. The returned URL SHALL be `/snapshots/{sessionId}.html`, served by NestJS static file middleware. File encoding SHALL be UTF-8.

#### Scenario: Local store writes file

- **GIVEN** the `LocalSnapshotStore` is configured
- **WHEN** `store("abc-123", "<html>...</html>")` is called
- **THEN** a file is created at `data/snapshots/abc-123.html`
- **AND** the file content matches the input HTML string
- **AND** the returned URL is `/snapshots/abc-123.html`

#### Scenario: Local store deletes file

- **GIVEN** a file exists at `data/snapshots/abc-123.html`
- **WHEN** `delete("abc-123")` is called
- **THEN** the file is removed from disk

#### Scenario: Local store handles missing file on delete

- **GIVEN** no file exists at `data/snapshots/xyz-999.html`
- **WHEN** `delete("xyz-999")` is called
- **THEN** no error is thrown

### Requirement: S3SnapshotStore uploads to S3 with correct metadata

The `S3SnapshotStore` SHALL upload HTML to `s3://{bucket}/snapshots/{sessionId}.html` with `Content-Type: text/html; charset=utf-8` and `Cache-Control: public, max-age=259200`. The returned URL SHALL be the CloudFront distribution URL.

#### Scenario: S3 upload with correct metadata

- **GIVEN** the `S3SnapshotStore` is configured with bucket `my-bucket` and CloudFront domain `d123.cloudfront.net`
- **WHEN** `store("abc-123", "<html>...</html>")` is called
- **THEN** `PutObject` is called with:
  - Key: `snapshots/abc-123.html`
  - Body: the HTML string
  - ContentType: `text/html; charset=utf-8`
  - CacheControl: `public, max-age=259200`
- **AND** the returned URL is `https://d123.cloudfront.net/snapshots/abc-123.html`

#### Scenario: S3 delete removes object

- **GIVEN** an object exists at `s3://my-bucket/snapshots/abc-123.html`
- **WHEN** `delete("abc-123")` is called
- **THEN** `DeleteObject` is called with Key: `snapshots/abc-123.html`

### Requirement: Provider selection via environment variable

The active `SnapshotStore` implementation SHALL be selected by the `SNAPSHOT_STORE` environment variable. If set to `s3`, the `S3SnapshotStore` is used. If set to `local` or unset, the `LocalSnapshotStore` is used.

#### Scenario: Default to local store

- **GIVEN** `SNAPSHOT_STORE` environment variable is not set
- **WHEN** the application starts
- **THEN** the `LocalSnapshotStore` is injected as the `SnapshotStore` provider

#### Scenario: S3 store selected

- **GIVEN** `SNAPSHOT_STORE=s3` environment variable is set
- **WHEN** the application starts
- **THEN** the `S3SnapshotStore` is injected as the `SnapshotStore` provider
