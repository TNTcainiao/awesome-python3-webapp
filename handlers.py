
import re, time, json, logging, hashlib, base64, asyncio
from aiohttp import web
from coroweb import get, post
from apis import APIError, APIValueError
from Models import User, Comment, Blog, next_id

@get('/')
def index(request):
    summary = 'Lorem ipsum dolor sit amet, consectetur adipisicing elit, sed do eiusmod tempor incididunt ut labore et dolore magna aliqua.'
    blogs = [
        Blog(id='1', name='Test Blog', summary=summary, created_at=time.time()-120),
        Blog(id='2', name='Something New', summary=summary, created_at=time.time()-3600),
        Blog(id='3', name='Learn Swift', summary=summary, created_at=time.time()-7200)
    ]
    return {
        '__template__': 'blogs.html',
        'blogs': blogs,
        '__user__': request.__user__
    }


@get('/register')                   #显示注册界面
def register():
    return {'__template__':'register.html'}

COOKIE_NAME = 'awesession'           #cookie名字
_COOKIE_KEY = 'heiheihei'            #cookie密钥


#制作cookie数值
def user2cookie(user,max_age):
    expires = str(int(time.time() + max_age))       #cookie到期时间
    s = '%s-%s-%s-%s' % (user.id, user.password, expires, _COOKIE_KEY)      #id，密码，到期时间，密钥
    L = [user.id,expires,hashlib.sha1(s.encode('utf-8')).hexdigest()]       #再进行hsha1加密

    return '-'.join(L)


#解析cookie数值
async def cookie2user(cookie_str):
    if not cookie_str:
        return None

    try:
        L = cookie_str.split('-')           #拆分字符串
        if len(L) != 3:
            return None
        uid,expires,sha1 = L
        if float(expires)<time.time():      #查看cookie是否过期
            return None
        user = await User.find(uid)         #从数据库中查找用户
        if not user:
            return None
        s = '%s-%s-%s-%s' % (uid,user.password,expires,'heiheihei')        #从数据库中生成哈希值
        if sha1 != hashlib.sha1(s.encode('utf-8')).hexdigest():     #与cookie中的哈希进行比较
            logging.info('invalid sha1')
            return None
        user.password = '******'
        return user
    except Exception as e:
        logging.info(e)
        return None

    #匹配邮箱和密码的正则表达式
_RE_EMAIL = re.compile(r'^[a-z0-9\.\-\_]+\@[a-z0-9\-\_]+(\.[a-z0-9\-\_]+){1,4}$')
_RE_SHA1 = re.compile(r'^[0-9a-f]{40}$')


@post('/api/users')                                     #用户注册API
async def api_register_user(*,email,name,passwd):
    if not name or not name.strip():
        raise APIValueError("name")
    if not email or not _RE_EMAIL.match(email):
        raise APIValueError('email')
    if not passwd or not _RE_SHA1.match(passwd):
        raise APIValueError('password')                 #对于注册信息的筛查

    users = await User.findAll(where='email=?',args=[email])        #查询邮箱是否已注册

    if len(users) > 0:
        raise APIError('register:failed','email','Email is already in use.')

    uid = next_id()
    sha1_password = '%s:%s' % (uid,passwd)
    user = User(id=uid,name=name.strip(),email=email,password=hashlib.sha1(sha1_password.encode('utf-8')).hexdigest(),image='http://www.gravatar.com/avatar/%s?d=mm&s=120' % hashlib.md5(email.encode('utf-8')).hexdigest())
    await user.save()                       #把注册的用户加入数据库

    r = web.Response()                      #制作Cookie返回给浏览器
    r.set_cookie(COOKIE_NAME,user2cookie(user,86400),max_age=86400,httponly=True)
    user.password = '******'
    r.content_type = 'application/json'
    r.body = json.dumps(user,ensure_ascii=False).encode('utf-8')
    return r


@get('/signin')                 #显示登陆界面
def signin():
    return {'__template__':'signin.html'}


@post('/api/authenticate')              #用户登陆API
async def authenticate(*,email,passwd):

    if not email:
        raise APIValueError('email')
    if not passwd:
        raise APIValueError('password')
    users = await User.findAll(where='email=?',args=[email])            #数据库中查询用户

    if len(users) == 0:
        raise APIValueError('email not exist')
    user = users[0]
    sha1 = hashlib.sha1()
    sha1.update(user.id.encode('utf-8'))
    sha1.update(b':')
    sha1.update(passwd.encode('utf-8'))             #将用户ID，密码构建成哈希值
    if sha1.hexdigest() != user.password:                 #如果不同，密码错误
        raise APIValueError('password is wrong')

    r = web.Response()                          #登陆成功给浏览器返回cookie
    r.set_cookie(COOKIE_NAME, user2cookie(user, 86400), max_age=86400, httponly=True)
    user.passwd = "******"
    r.content_type = 'application/json'
    r.body = json.dumps(user, ensure_ascii=False).encode('utf-8')
    return r


@get('/api/users123')
async def api_get_users():
    users = await User.findAll(orderBy='created_at desc')
    for u in users:
        u.passwd = '******'
    return dict(users=users)


@get('/signout')                                #用户登出API
def signout(request):
    referer = request.headers.get('Referer')
    r = web.HTTPFound(referer or '/')
    r.set_cookie(COOKIE_NAME, '-deleted-', max_age=0, httponly=True)        #移除cookie信息
    logging.info('user signed out.')
    return r


def check_admin(request):
    if request.__user__ is None or not  request.__user__.admin:
        raise APIValueError('123456')

@post('/api/blogs')
async def api_create_blogs(request,*,name,summary,content):
    check_admin(request)
    logging.info('11111111111111')
    if not name or not name.strip():
        raise APIValueError('name','name can not empty')
    if not summary or not summary.strip():
        raise APIValueError('summary','summary can not empty.')
    if not content or not content.strip():
        raise APIValueError('content','content can not empty.')
    blog = Blog(user_id=request.__user__.id,user_name=request.__user__.name,user_image=request.__user__.image,summary=summary.strip(),name=name.strip(),content=content.strip())

    await blog.save()
    return blog


#显示创建blog页面
@get('/manage/blogs/create')
def manage_create_blog(request):
    return {
        '__template__': 'manage_blog_edit.html',
        'id': '',
        'action': '/api/blogs',
        '__user__': request.__user__
    }


