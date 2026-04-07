from utils.encryption import encrypt_text, decrypt_text
import pytest

def test_encryption_determinism():
    """
    Tests that a string passed through the Fernet symmetric 
    encryption layer accurately deserializes back to its raw form.
    """
    raw_payload = "1/oauth_test_refresh_token_string_89324"
    encrypted = encrypt_text(raw_payload)
    
    assert encrypted != raw_payload
    # The output should be a decodable ASCII base64 string
    assert isinstance(encrypted, str)
    
    decrypted = decrypt_text(encrypted)
    assert decrypted == raw_payload

def test_encryption_edge_cases():
    """
    Edge case: Empty inputs.
    """
    assert decrypt_text(encrypt_text("")) == ""
    
    # Edge case: Invalid Fernet token should raise an error
    with pytest.raises(Exception):
        decrypt_text("invalid_fernet_token")
