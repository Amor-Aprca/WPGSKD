from abc import ABC, abstractmethod

class Decryptor(ABC):
    @abstractmethod
    def decrypt(self, data: bytes, **kwargs) -> bytes:
        pass