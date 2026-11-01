"""Default profile and email template (taken from Shubham's CV). All editable in the UI."""

DEFAULT_PROFILE = {
    "name": "Shubham Kumar",
    "role": "Senior DevOps & Cloud Engineer",
    "experience": "5 years 9 months",
    "phone": "+91 8809783125",
    "linkedin": "https://linkedin.com/in/shubham-kumar-0201199b9",
    "portfolio": "https://shubh-portfolio-cloud.vercel.app",
    "email": "contact.shubham2702@gmail.com",
}

# domain-core -> display name, for domains whose company name can't be guessed well
DEFAULT_OVERRIDES = {
    "tcs": "Tata Consultancy Services",
    "hcltech": "HCLTech",
    "ltimindtree": "LTIMindtree",
    "techm": "Tech Mahindra",
}

DEFAULT_SUBJECT = "Application for DevOps / Cloud Engineer role - {my_name} (AWS | Azure | Terraform | Kubernetes)"

DEFAULT_BODY = """{greeting}

I am {my_name}, a {role} with {experience} of experience running production platforms on AWS and Azure using Terraform, Kubernetes (EKS/AKS), Docker and CI/CD (Jenkins, GitHub Actions). I hold the AWS Certified Solutions Architect - Associate certification.

Highlights from my current role at Wipro:
- Cut infrastructure provisioning effort by 60%+ through Terraform automation
- Reduced deployment time by 40-50% with CI/CD and containerization
- Achieved 15-25% cloud cost optimization through right-sizing and monitoring
- Built observability (Datadog, Grafana, CloudWatch) and RCA practices that reduced repeat incidents

I am interested in DevOps, Cloud and SRE roles{at_company}.

{context}

I have attached my resume for your review and would welcome the chance to discuss how I can contribute to your team.

You can reach me on {phone}, or see my profile at {linkedin} and my portfolio at {portfolio}.

Thank you for your time.

Best regards,
{my_name}
{role}
{phone}

P.S. If this is not relevant, just reply and I will not write again."""
