from Cryptodome.Cipher import AES
from wpgskd.core.decryptors.base import Decryptor

class AES128Decryptor(Decryptor):
    
    def __init__(self, key: bytes, iv: bytes = None):
        self.key = key
        self.iv = iv

    def decrypt(self, data: bytes, sequence_number: int = 0, **kwargs) -> bytes:
        current_iv = self.iv
        if not current_iv:
            current_iv = sequence_number.to_bytes(16, 'big')
            
        cipher = AES.new(self.key, AES.MODE_CBC, current_iv)
        
        try:
            return cipher.decrypt(data)
        except ValueError:
            return data