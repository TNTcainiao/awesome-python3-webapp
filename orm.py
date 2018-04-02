import asyncio, logging; logging.basicConfig(level=logging.INFO)
import aiomysql


async def create_pool(loop,**kw):                       #创建连接池，方便多次获取数据库连接
    logging.info('create database connection pool...')
    global _pool                                        #声明全局变量--连接池
    _pool = await aiomysql.create_pool(

        host=kw.get('host', 'localhost'),
        port=kw.get('port', '3306'),
        user=kw['user'],
        password=kw['password'],
        db=kw['db'],
        charset=kw.get('charset', 'utf8'),
        autocommit=kw.get('autocommit',True),
        maxsize=kw.get('maxsize', 10),                 #池的最大大小
        minsize=kw.get('mainsize', 1),
        loop=loop                                      #可选的事件循环

    )


def log(sql, args=()):
    logging.info('SQL:{}'.format(sql))             #对logging封装，方便输出sql语句


async def select(sql,args,size=None):              #封装查询事务，第一个参数为sql语句,第二个为sql语句中占位符的参数列表,第三个参数是要查询数据的数量

    log(sql, args)

    async with _pool.acquire() as conn:                             #通过连接池获取数据库连接
        async with conn.cursor(aiomysql.DictCursor) as cur:         #获取游标,默认游标返回的结果为元组,每一项是另一个元组,这里可以指定元组的元素为字典通过aiomysql.DictCursor
                                                                    #调用游标的execute()方法来执行sql语句,execute()接收两个参数,第一个为sql语句可以包含占位符,第二个为占位符对应的值,使用该形式可以避免直接使用字符串拼接出来的sql的注入攻击
            await cur.execute(sql.replace('?','%s'),args or ())     #sql语句的占位符为?,mysql里为%s,做替换
            if size:
                rs = await cur.fetchmany(size)                      #size有值就获取对应数量的数据
            else:
                rs = await cur.fetchall()                           #获取所有数据库中的所有数据,此处返回的是一个数组,数组元素为字典

        logging.info('rows returned: {}'.format(len(rs)))
        return rs


async def execute(sql,args,autocommit=True):       #该协程封装了增删改的操作
    log(sql)

    async with _pool.acquire() as conn:
        if not autocommit:                          #如果不是自动提交事务,需要手动启动,但是我发现这个是可以省略的
            await conn.begin()

        try:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(sql.replace('?','%s'),args)
                affected = cur.rowcount
            if not autocommit:
                await conn.commit()
        except BaseException as e:
            if not autocommit:
                await conn.rollback()                   #回滚,在执行commit()之前如果出现错误,就回滚到执行事务前的状态,以免影响数据库的完整性
            raise
        return affected


def create_args_string(num):                    #创建拥有几个占位符的字符串
    L = []
    for n in range(num):
        L.append('?')
    return ','.join(L)


class Field(object):                                     #该类是为了保存 数据库列名 和 类型 的基类
    def __init__(self,name,column_type,primary_key,defalut):
        self.name = name                                 #列名
        self.column_type = column_type                   #数据类型
        self.primary_key = primary_key                   #是否为主键
        self.default = defalut                           #默认值

    def __str__(self):
        return '{}, {}:{}'.format(self.__class__.__name__,self.column_type,self.name)


class StringField(Field):                               #字符型 列名
    def __init__(self,name=None,primary_key=False,default=None,ddl='varchar(100)'):
        super().__init__(name,ddl,primary_key,default)


class BooleanField(Field):                              #布尔型 列名
    def __init__(self,name=None,default=False):
        super().__init__(name,'boolean',False,default)


class IntegerField(Field):                              #整数型 列名
    def __init__(self,name=None,primary_key=False,default=0):
        super().__init__(name,'bigint',primary_key,default)


class FloatField(Field):                                #整数型 列名

    def __init__(self, name=None, primary_key=False, default=0.0):
        super().__init__(name, 'real', primary_key, default)


class TextField(Field):                                 #文本型 列名
    def __init__(self, name=None, default=None):
        super().__init__(name, 'text', False, default)


class ModeMetaclass(type):                              #元类

    def __new__(cls, name, bases, attrs):
        if name == 'Model':                             #如果是基类，不做处理，没有字段名
            return type.__new__(cls, name, bases, attrs)

        tableName = attrs.get('__table__',None) or name                         #保存表名,如果获取不到,则把类名当做表名,完美利用了or短路原理
        logging.info('found model : {} (table {})'.format(name,tableName))

        mappings = dict()                               #存储属性名和字段信息的映射关系

        fields = []                                     #保存列名的列表

        primaryKey = None                               #主键

        for k, v in attrs.items():                      #遍历attrs（类的所有属性），k为属性名，v为该属性对应的字段信息
            if isinstance(v,Field):                     #是列名就保存进列类型的字典
                logging.info('found mappings:{} ==> {}'.format(k,v))
                mappings[k] = v
                if v.primary_key:                       #找到主键
                    if primaryKey:
                        raise StandardError('Duplicate primary key for field: {}'.format(k))
                    primaryKey = k
                else:
                    fields.append(k)                    #非主键列名保存进列表

        if not primaryKey:
            raise StandardError('primary key not found')    #没找到主键

        for k in mappings.keys():
            attrs.pop(k)                                #清空attrs
        escaped_fields = list(map(lambda f: '`{}`'.format(f), fields))          #将fields中属性名以`属性名`的方式装饰起来

        #重新设置attrs，类的属性和方法都放在fields，主键属性放在primary_key

        attrs['__mappings__'] = mappings
        attrs['__table__'] = tableName
        attrs['__primary_key__'] = primaryKey
        attrs['__fields__'] = fields

        #以下四种方法保存了默认了增删改查操作,其中添加的反引号``,是为了避免与sql关键字冲突的,否则sql语句会执行出错

        attrs['__select__'] = 'select `{}`, {} from `{}`'.format(primaryKey, ', '.join(escaped_fields), tableName)
        attrs['__insert__'] = 'insert into `{}` ({}, `{}`) values ({})'.format(tableName, ', '.join(escaped_fields), primaryKey, create_args_string(len(escaped_fields) + 1))
        attrs['__update__'] = 'update `{}` set {} where `{}`=?'.format(tableName, ', '.join(map(lambda f: '`{}`=?'.format(mappings.get(f).name or f), fields)), primaryKey)
        attrs['__delete__'] = 'delete from `{}` where `{}`=?'.format(tableName, primaryKey)
        return type.__new__(cls,name,bases,attrs)



class Model(dict,metaclass=ModeMetaclass):      #这是模型的基类,继承于dict,主要作用就是如果通过点语法来访问对象的属性获取不到的话,可以定制__getattr__来通过key来再次获取字典里的值
    def __init__(self,**kw):
        super().__init__(**kw)

    def __getattr__(self, key):
        try:
            return self[key]
        except KeyError:
            raise AttributeError(r"'Model' object has no attribute '{}'".format(key))

    def __setattr__(self, key, value):
        self[key] = value

    def getValue(self,key):                             #调用getattr获取一个未存在的属性,也会走__getattr__方法,但是因为指定了默认返回的值,__getattr__里面的错误永远不会抛出
        return getattr(self,key,None)

    def getValueOrDefault(self,key):                    #使用默认值
        value = getattr(self,key,None)
        if value is None:
            field = self.__mappings__[key]              # 从mappings映射集合中找默认值
            if field.default is not None:
                value = field.default() if callable(field.default) else field.default
                logging.debug('using default value for %s: %s' % (key, str(value)))
                setattr(self,key,value)
        return value


    @classmethod
    async def findAll(cls, where=None, args=None,**kw):
        '''
            通过where查找多条记录对象
            :param where:where查询条件
            :param args:sql参数
            :param kw:查询条件列表
            :return:多条记录集合
        '''
        sql = [cls.__select__]
        if where:
            sql.append('where')
            sql.append(where)

        if args is None:
            args = []

        orderBy = kw.get('orderBy',None)
        if orderBy:
            sql.append('order by')
            sql.append(orderBy)

        limit = kw.get('limit',None)
        if limit is not None:
            sql.append('limit')
            if isinstance(limit,int):
                sql.append('?')
                args.append(limit)
            elif isinstance(limit,tuple) and len(limit) == 2:
                sql.append('?,?')
                args.extend(limit)
            else:
                raise ValueError('Invalid limit value: {}'.format(str(limit)))

        rs = await select(' '.join(sql),args)

        return [cls(**r) for r in rs]


    @classmethod
    async def findNumber(cls, selectField, where=None, args=None):
        '''
            查询某个字段的数量
            :param selectField: 要查询的字段
            :param where: where查询条件
            :param args: 参数列表
            :return: 数量
        '''
        sql = ['select count({}) _num_ from `{}`'.format(selectField,cls.__table__)]
        if where:
            sql.append('where')
            sql.append(where)
        rs = await select(' '.join(sql),args,1)
        return rs[0]['_num_']


    @classmethod
    async def find(cls,pk):
        '''
            通过id查询
            :param pk:id
            :return: 一条记录
        '''
        rs = await select('{} where `{}`=?'.format(cls.__select__,cls.__primary_key__),[pk],1)
        if len(rs) == 0:
            return None
        return cls(**rs[0])


    #一下的都是对象方法,所以可以不用传任何参数,方法内部可以使用该对象的所有属性,及其方便

    async def save(self):                                   #保存实例（记录）到数据库

        args = list(map(self.getValueOrDefault,self.__fields__))         #得到对应字段的值
        args.append(self.getValueOrDefault(self.__primary_key__))       #主键值
        rows = await execute(self.__insert__,args)
        if rows != 1:
            logging.warning('failed to insert record: affected rows: {}'.format(rows))

    async def update(self):                                 #更新记录
        args = list(map(self.getValue, self.__fields__))
        args.append(self.getValue(self.__primary_key__))
        rows = await execute(self.__update__, args)
        if rows != 1:
            logging.warning('failed to update by primary key: affected rows: {}'.format(rows))

    async def remove(self):                                 #删除一条记录
        args = [self.getValue(self.__primary_key__)]
        rows = await execute(self.__delete__, args)
        if rows != 1:
            logging.warning('failed to remove by primary key: affected rows: %s'.format(rows))






























