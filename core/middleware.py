class PrivateResponseMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if not request.path.startswith('/static/'):
            response['Cache-Control'] = 'no-store, private'
            response['Content-Security-Policy'] = ("default-src 'self'; style-src 'self'; script-src 'self'; "
                                                   "img-src 'self' data:; object-src 'none'; base-uri 'self'; "
                                                   "frame-ancestors 'none'; form-action 'self'")
        return response
