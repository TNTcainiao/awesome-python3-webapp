
import re, time, json, logging, hashlib, base64, asyncio

from coroweb import get, post

from Models import User, Comment, Blog, next_id

@get('/')
async def index(request):
    users = await User.findAll()
    return {
        '__template__': 'test.html',
        'users': users
    }


@get('/hello')
async def hello(request):
    return '<h1>hello!</h1>'


