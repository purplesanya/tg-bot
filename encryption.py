"""
RSA + AES Hybrid Encryption Module for sensitive data
"""

from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend
import base64
import os

RSA_PRIVATE_KEY_FILE = 'rsa_private_key.pem'
RSA_PUBLIC_KEY_FILE = 'rsa_public_key.pem'

def generate_rsa_keys():
    """Generate RSA key pair if not exists"""
    if os.path.exists(RSA_PRIVATE_KEY_FILE) and os.path.exists(RSA_PUBLIC_KEY_FILE):
        return

    # Generate private key
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
        backend=default_backend()
    )

    # Save private key
    with open(RSA_PRIVATE_KEY_FILE, 'wb') as f:
        f.write(private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption()
        ))

    # Save public key
    public_key = private_key.public_key()
    with open(RSA_PUBLIC_KEY_FILE, 'wb') as f:
        f.write(public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo
        ))

    # Set secure permissions
    os.chmod(RSA_PRIVATE_KEY_FILE, 0o600)
    os.chmod(RSA_PUBLIC_KEY_FILE, 0o644)

    print("✅ RSA keys generated successfully")

def load_private_key():
    """Load private key from file"""
    with open(RSA_PRIVATE_KEY_FILE, 'rb') as f:
        return serialization.load_pem_private_key(
            f.read(),
            password=None,
            backend=default_backend()
        )

def load_public_key():
    """Load public key from file"""
    with open(RSA_PUBLIC_KEY_FILE, 'rb') as f:
        return serialization.load_pem_public_key(
            f.read(),
            backend=default_backend()
        )

def encrypt_data(data: str) -> str:
    """
    Hybrid encryption: AES for data, RSA for AES key
    This allows encrypting large data (like session strings)
    """
    if not data:
        return None

    try:
        public_key = load_public_key()

        # Generate random AES key
        aes_key = os.urandom(32)  # 256-bit key
        iv = os.urandom(16)  # 128-bit IV

        # Encrypt data with AES
        cipher = Cipher(
            algorithms.AES(aes_key),
            modes.CBC(iv),
            backend=default_backend()
        )
        encryptor = cipher.encryptor()

        # Pad data to AES block size
        data_bytes = data.encode('utf-8')
        padding_length = 16 - (len(data_bytes) % 16)
        padded_data = data_bytes + bytes([padding_length] * padding_length)

        # Encrypt with AES
        encrypted_data = encryptor.update(padded_data) + encryptor.finalize()

        # Encrypt AES key with RSA
        encrypted_key = public_key.encrypt(
            aes_key,
            padding.OAEP(
                mgf=padding.MGF1(algorithm=hashes.SHA256()),
                algorithm=hashes.SHA256(),
                label=None
            )
        )

        # Combine: encrypted_key_length (2 bytes) + encrypted_key + iv + encrypted_data
        key_length = len(encrypted_key).to_bytes(2, byteorder='big')
        combined = key_length + encrypted_key + iv + encrypted_data

        # Return base64 encoded
        return base64.b64encode(combined).decode('utf-8')

    except Exception as e:
        print(f"Encryption error: {e}")
        # Fallback to simple RSA for short strings
        if len(data.encode('utf-8')) < 190:  # RSA 2048 can encrypt up to ~190 bytes
            try:
                data_bytes = data.encode('utf-8')
                encrypted = public_key.encrypt(
                    data_bytes,
                    padding.OAEP(
                        mgf=padding.MGF1(algorithm=hashes.SHA256()),
                        algorithm=hashes.SHA256(),
                        label=None
                    )
                )
                return 'RSA:' + base64.b64encode(encrypted).decode('utf-8')
            except:
                raise Exception("Data too large to encrypt")
        raise

def decrypt_data(encrypted_data: str) -> str:
    """
    Decrypt hybrid encrypted data
    """
    if not encrypted_data:
        return None

    try:
        private_key = load_private_key()

        # Check if it's simple RSA (fallback format)
        if encrypted_data.startswith('RSA:'):
            encrypted_bytes = base64.b64decode(encrypted_data[4:].encode('utf-8'))
            decrypted = private_key.decrypt(
                encrypted_bytes,
                padding.OAEP(
                    mgf=padding.MGF1(algorithm=hashes.SHA256()),
                    algorithm=hashes.SHA256(),
                    label=None
                )
            )
            return decrypted.decode('utf-8')

        # Decode base64
        combined = base64.b64decode(encrypted_data.encode('utf-8'))

        # Extract components
        key_length = int.from_bytes(combined[0:2], byteorder='big')
        encrypted_key = combined[2:2+key_length]
        iv = combined[2+key_length:2+key_length+16]
        encrypted_data_bytes = combined[2+key_length+16:]

        # Decrypt AES key with RSA
        aes_key = private_key.decrypt(
            encrypted_key,
            padding.OAEP(
                mgf=padding.MGF1(algorithm=hashes.SHA256()),
                algorithm=hashes.SHA256(),
                label=None
            )
        )

        # Decrypt data with AES
        cipher = Cipher(
            algorithms.AES(aes_key),
            modes.CBC(iv),
            backend=default_backend()
        )
        decryptor = cipher.decryptor()
        padded_data = decryptor.update(encrypted_data_bytes) + decryptor.finalize()

        # Remove padding
        padding_length = padded_data[-1]
        data_bytes = padded_data[:-padding_length]

        # Return string
        return data_bytes.decode('utf-8')

    except Exception as e:
        print(f"Decryption error: {e}")
        raise

# Initialize keys on import
generate_rsa_keys()