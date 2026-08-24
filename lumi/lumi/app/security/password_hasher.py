import hashlib, secrets

class PasswordHasher:
    def __init__(self, iterations: int = 200_000):
        self.iterations = iterations

    def hash_password(self, password: str) -> dict:
        salt = secrets.token_hex(16)
        digest = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), self.iterations)
        return {"algorithm":"pbkdf2_sha256","iterations":self.iterations,"salt":salt,"hash":digest.hex()}

    def verify_password(self, password: str, hash_record: dict) -> bool:
        try:
            salt = hash_record['salt']; iterations = int(hash_record.get('iterations', self.iterations)); expected = hash_record['hash']
            digest = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), iterations).hex()
            return secrets.compare_digest(digest, expected)
        except Exception:
            return False

    def validate_password_strength(self, password: str) -> dict:
        warnings=[]
        if len(password or '') < 8:
            return {"valid":False,"errors":["Password must be at least 8 characters"],"warnings":warnings}
        if password.lower() in {"password","admin","12345678","qwerty123"}:
            return {"valid":False,"errors":["Password is too common"],"warnings":warnings}
        if len(password) < 12: warnings.append("Password is relatively short; consider 12+ characters")
        if not any(c.isupper() for c in password): warnings.append("Consider adding uppercase letters")
        if not any(c.isdigit() for c in password): warnings.append("Consider adding numbers")
        return {"valid":True,"errors":[],"warnings":warnings}
