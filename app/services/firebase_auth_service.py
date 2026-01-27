import os
from firebase_admin import auth, firestore
from typing import Optional, Dict, Any
from app.services.firebase_service import firebase_service


class FirebaseAuthService:
    """Service for Firebase Authentication operations"""
    
    async def create_hospital_user(
        self,
        email: str,
        password: str,
        hospital_name: str,
        address: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Create a new hospital user with email/password
        
        Returns:
            Dict with success status, hospital_id, and any error messages
        """
        try:
            # Create Firebase Auth user
            user = auth.create_user(
                email=email,
                password=password,
                display_name=hospital_name
            )
            
            # Generate hospital ID from UID
            hospital_id = f"hospital_{user.uid}"
            
            # Save hospital data to Firestore
            hospital_data = {
                "id": hospital_id,
                "name": hospital_name,
                "email": email,
                "address": address or "",
                "firebase_uid": user.uid,
                "created_at": firestore.SERVER_TIMESTAMP
            }
            
            await firebase_service.save_hospital(hospital_id, hospital_data)
            
            return {
                "success": True,
                "hospital_id": hospital_id,
                "uid": user.uid,
                "email": email
            }
            
        except auth.EmailAlreadyExistsError:
            return {
                "success": False,
                "error": "An account with this email already exists"
            }
        except Exception as e:
            print(f"Error creating hospital user: {e}")
            return {
                "success": False,
                "error": str(e)
            }
    
    async def create_doctor_user(
        self,
        email: str,
        password: str,
        name: str,
        specialty: Optional[str] = None,
        hospital_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Create a new doctor user with email/password
        
        Returns:
            Dict with success status, doctor_id, and any error messages
        """
        try:
            # Create Firebase Auth user
            user = auth.create_user(
                email=email,
                password=password,
                display_name=name
            )
            
            # Generate doctor ID from UID
            doctor_id = f"doctor_{user.uid}"
            
            # Save doctor data to Firestore
            doctor_data = {
                "id": doctor_id,
                "name": name,
                "email": email,
                "specialty": specialty or "General Practice",
                "hospital_id": hospital_id,
                "firebase_uid": user.uid,
                "linked_at": firestore.SERVER_TIMESTAMP
            }
            
            await firebase_service.save_doctor_credentials(doctor_id, doctor_data)
            
            return {
                "success": True,
                "doctor_id": doctor_id,
                "uid": user.uid,
                "email": email
            }
            
        except auth.EmailAlreadyExistsError:
            return {
                "success": False,
                "error": "An account with this email already exists"
            }
        except Exception as e:
            print(f"Error creating doctor user: {e}")
            return {
                "success": False,
                "error": str(e)
            }
    
    async def verify_custom_token(self, id_token: str) -> Optional[Dict[str, Any]]:
        """
        Verify Firebase ID token from client
        
        Returns:
            User data if valid, None if invalid
        """
        try:
            decoded_token = auth.verify_id_token(id_token)
            uid = decoded_token['uid']
            email = decoded_token.get('email')
            
            # Check if user is hospital or doctor
            hospital = await firebase_service.get_hospital(f"hospital_{uid}")
            if hospital:
                return {
                    "type": "hospital",
                    "id": hospital["id"],
                    "email": email,
                    "uid": uid
                }
            
            doctor = await firebase_service.get_doctor(f"doctor_{uid}")
            if doctor:
                return {
                    "type": "doctor",
                    "id": doctor.get("id"),
                    "email": email,
                    "uid": uid
                }
            
            return None
            
        except Exception as e:
            print(f"Error verifying token: {e}")
            return None
    
    async def get_user_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        """Get user by email from Firebase Auth"""
        try:
            user = auth.get_user_by_email(email)
            return {
                "uid": user.uid,
                "email": user.email,
                "display_name": user.display_name
            }
        except auth.UserNotFoundError:
            return None
        except Exception as e:
            print(f"Error getting user by email: {e}")
            return None
    
    async def delete_user(self, uid: str) -> bool:
        """Delete user from Firebase Auth"""
        try:
            auth.delete_user(uid)
            return True
        except Exception as e:
            print(f"Error deleting user: {e}")
            return False


# Singleton instance
firebase_auth_service = FirebaseAuthService()


"""
TODO: Enterprise SSO/SAML Implementation Plan for Hospital Authentication

Current Implementation:
- Basic email/password authentication using Firebase Auth
- Suitable for small clinics and individual hospitals

Recommended Upgrades for Enterprise:

1. SAML 2.0 Integration:
   - Integrate with enterprise Identity Providers (Okta, Azure AD, OneLogin)
   - Benefits: Centralized user management, single sign-on, compliance
   - Implementation: Use Firebase Auth SAML provider or custom SAML library
   
2. OAuth 2.0 / OpenID Connect:
   - Support for enterprise OAuth providers
   - Better for modern cloud-native organizations
   - Firebase supports Google, Microsoft, custom OIDC providers
   
3. Multi-Factor Authentication (MFA):
   - Add SMS, authenticator app, or hardware token support
   - Firebase Auth supports built-in MFA
   - Critical for healthcare data security (HIPAA compliance)
   
4. Role-Based Access Control (RBAC):
   - Implement custom claims in Firebase Auth tokens
   - Define roles: admin, doctor, receptionist, billing, etc.
   - Granular permissions per resource
   
5. Audit Logging:
   - Track all authentication events
   - Store in separate audit collection in Firestore
   - Required for compliance (HIPAA, GDPR)
   
6. Session Management:
   - Implement session timeouts
   - Force re-authentication for sensitive operations
   - Concurrent session limits
   
7. IP Whitelisting:
   - Restrict access to known hospital networks
   - Implement in Cloud Armor or API Gateway level
   
8. Security Considerations:
   - Regular security audits
   - Penetration testing
   - Keep all dependencies updated
   - Implement rate limiting on auth endpoints
   - Use HTTPS only (already enforced)
   
Implementation Priority (for healthcare enterprise):
Priority 1: MFA, Audit Logging
Priority 2: SAML/SSO, RBAC
Priority 3: IP Whitelisting, Advanced session management

Estimated Timeline:
- MFA: 1-2 weeks
- SAML Integration: 2-4 weeks
- Full RBAC: 2-3 weeks
- Audit System: 1-2 weeks

Cost Considerations:
- Firebase Auth Blaze plan: Pay-as-you-go
- Enterprise SSO providers: $3-10 per user/month
- Security audit: $5,000-$20,000

Compliance Requirements:
- HIPAA: Audit logs, MFA, encryption at rest/transit
- GDPR: Data privacy, right to deletion, consent management
- SOC 2: Access controls, monitoring, incident response
"""