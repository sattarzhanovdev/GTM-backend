from unittest.mock import Mock, patch

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from api.auth import issue_token
from api.models import ComplexBuilding, PaymentCharge, PaymentParticipation, Profile, ResidentialComplex


class PaymentsAttachReceiptTests(TestCase):
    def setUp(self):
        self.complex, _ = ResidentialComplex.objects.get_or_create(slug="nasip", defaults={"title": "Эл Насип"})
        self.building, _ = ComplexBuilding.objects.get_or_create(
            complex=self.complex,
            building_id="20",
            defaults={"title": "20"},
        )
        self.user = User.objects.create_user(username="nasip-20-4-220", password="secret123")
        self.profile, _ = Profile.objects.get_or_create(
            user=self.user,
            defaults={
                "complex": self.complex,
                "building": self.building,
                "apartment": 220,
                "entrance": 4,
            },
        )
        self.payment = PaymentCharge.objects.create(
            complex=self.complex,
            building=self.building,
            service_name="Тестовая оплата",
            amount=500,
            currency="сом",
        )
        self.auth_header = {"HTTP_AUTHORIZATION": f"Bearer {issue_token(self.user.username)}"}

    def _post_receipt(self):
        upload = SimpleUploadedFile("receipt.png", b"fake-image-content", content_type="image/png")
        return self.client.post(f"/api/payments/{self.payment.id}/receipt/", {"file": upload}, **self.auth_header)

    @patch("api.views.requests.post")
    def test_fake_receipt_stays_pending(self, mock_post):
        mock_response = Mock()
        mock_response.json.return_value = {"is_fake": True}
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response

        response = self._post_receipt()

        self.assertEqual(response.status_code, 200)
        participation = PaymentParticipation.objects.get(payment=self.payment, building=self.building, apartment=220)
        self.assertEqual(participation.status, PaymentParticipation.Status.PENDING)

    @patch("api.views.requests.post")
    def test_real_receipt_becomes_accepted(self, mock_post):
        mock_response = Mock()
        mock_response.json.return_value = {"is_fake": False}
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response

        response = self._post_receipt()

        self.assertEqual(response.status_code, 200)
        participation = PaymentParticipation.objects.get(payment=self.payment, building=self.building, apartment=220)
        self.assertEqual(participation.status, PaymentParticipation.Status.ACCEPTED)
