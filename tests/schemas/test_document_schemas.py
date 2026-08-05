from unittest.mock import MagicMock, patch


def test_document_read_resolves_legacy_file_url_unchanged():
    from app.schemas.document import DocumentRead

    data = {
        "id": 1,
        "source": "deal",
        "entity_id": 5,
        "entity_name": "Acme Deal",
        "file_name": "proposal.pdf",
        "file_url": "/media/deal_documents/5_abc123.pdf",
        "content_type": "application/pdf",
        "uploaded_by": 2,
        "created_at": "2026-01-01T00:00:00",
    }
    doc = DocumentRead.model_validate(data)
    assert doc.file_url == "/media/deal_documents/5_abc123.pdf"


@patch("app.services.s3_storage_service.boto3.client")
def test_document_read_resolves_s3_key_to_presigned_url(mock_boto_client):
    from app.schemas.document import DocumentRead

    mock_client = MagicMock()
    mock_client.generate_presigned_url.return_value = "https://example.com/signed"
    mock_boto_client.return_value = mock_client

    data = {
        "id": 1,
        "source": "deal",
        "entity_id": 5,
        "entity_name": "Acme Deal",
        "file_name": "proposal.pdf",
        "file_url": "deal_documents/5_abc123.pdf",
        "content_type": "application/pdf",
        "uploaded_by": 2,
        "created_at": "2026-01-01T00:00:00",
    }
    doc = DocumentRead.model_validate(data)
    assert doc.file_url == "https://example.com/signed"
