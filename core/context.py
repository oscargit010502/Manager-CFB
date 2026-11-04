from .models import Company

def company_context(request):
    return {'company': Company.objects.first()} if request.user.is_authenticated else {}
