import unittest
import tests.conftest  # noqa: F401  (adds project root to sys.path)
from company import guess_company, make_greeting, resolve_company


class TestCompany(unittest.TestCase):
    def test_domains(self):
        cases = {
            "hr@tata-consultancy.com": ("Tata Consultancy", True),
            "jobs@infosys.com": ("Infosys", True),
            "careers@globex.co.in": ("Globex", True),
            "talent@mail.initech.io": ("Initech", True),
            "hr@tcs.com": ("TCS", True),
            "x@my_cool_startup.ai": ("My Cool Startup", True),
            "x@bbc.co.uk": ("BBC", True),
            "x@acme.com.au": ("Acme", True),
            "x@hr.zoho.com": ("Zoho", True),
            "x@gmail.com": ("", False),
            "x@yahoo.co.in": ("", False),
            "x@outlook.com": ("", False),
            "x@hotmail.com": ("", False),
            "x@rediffmail.com": ("", False),
        }
        for email, want in cases.items():
            self.assertEqual(guess_company(email), want, email)

    def test_override_and_provided(self):
        self.assertEqual(guess_company("a@tcs.com", {"tcs": "Tata Consultancy Services"}),
                         ("Tata Consultancy Services", True))
        self.assertEqual(resolve_company("a@tcs.com", "My Corp"), ("My Corp", True))

    def test_greeting(self):
        self.assertEqual(make_greeting("Priya Sharma", "Globex", True), "Dear Priya Sharma,")
        self.assertEqual(make_greeting("", "Globex", True), "Dear Hiring Team at Globex,")
        self.assertEqual(make_greeting("", "", False), "Dear Hiring Team,")
        self.assertEqual(make_greeting("  ", "Acme", True), "Dear Hiring Team at Acme,")


if __name__ == "__main__":
    unittest.main()
