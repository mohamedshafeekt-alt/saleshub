from unittest.mock import MagicMock, patch


def test_account_document_read_resolves_legacy_file_url_unchanged():
    from app.schemas.account_document import AccountDocumentRead

    data = {
        "id": 1,
        "account_id": 5,
        "file_name": "nda.pdf",
        "file_url": "/media/account_documents/5_abc123.pdf",
        "content_type": "application/pdf",
        "uploaded_by": 2,
        "created_at": "2026-01-01T00:00:00",
    }
    doc = AccountDocumentRead.model_validate(data)
    assert doc.file_url == "/media/account_documents/5_abc123.pdf"


@patch("app.services.s3_storage_service.boto3.client")
def test_account_document_read_resolves_s3_key_to_presigned_url(mock_boto_client):
    from app.schemas.account_document import AccountDocumentRead

    mock_client = MagicMock()
    mock_client.generate_presigned_url.return_value = "https://example.com/signed"
    mock_boto_client.return_value = mock_client

    data = {
        "id": 1,
        "account_id": 5,
        "file_name": "nda.pdf",
        "file_url": "account_documents/5_abc123.pdf",
        "content_type": "application/pdf",
        "uploaded_by": 2,
        "created_at": "2026-01-01T00:00:00",
    }
    doc = AccountDocumentRead.model_validate(data)
    assert doc.file_url == "https://example.com/signed"
