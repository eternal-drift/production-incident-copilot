"""
Shared Limiter instance. Split out from app/main.py so routers can import
it without a circular import (main.py imports the routers, routers need
the limiter to decorate their endpoints).
"""
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
