"""
MongoDB model fields emulating Django Extensions' additional model fields

These fields are essentially identical to existing Extensions fields, but South hooks have been removed (since mongo requires no schema migration)

"""

import six
from django.template.defaultfilters import slugify
from django import forms
from mongoengine.fields import StringField, DateTimeField
import datetime
import re
from django.utils.translation import ugettext_lazy as _

try:
    import uuid
    assert uuid
except ImportError:
    from django_extensions.utils import uuid


class SlugField(StringField):
    description = _("String (up to %(max_length)s)")

    def __init__(self, *args, **kwargs):
        kwargs['max_length'] = kwargs.get('max_length', 50)
        # Set db_index=True unless it's been set manually.
        #if 'db_index' not in kwargs:
        #    kwargs['db_index'] = True
        super(SlugField, self).__init__(*args, **kwargs)

    def get_internal_type(self):
        return "SlugField"

    def formfield(self, **kwargs):
        defaults = {'form_class': forms.SlugField}
        defaults.update(kwargs)
        return super(SlugField, self).formfield(**defaults)


class AutoSlugField(SlugField):
    """ AutoSlugField, adapted for MongoDB

    By default, sets editable=False, blank=True.

    Required arguments:

    populate_from
        Specifies which field or list of fields the slug is populated from.

    Optional arguments:

    separator
        Defines the used separator (default: '-')

    overwrite
        If set to True, overwrites the slug on every save (default: False)

    Inspired by SmileyChris' Unique Slugify snippet:
    http://www.djangosnippets.org/snippets/690/
    """
    def __init__(self, *args, **kwargs):
        #kwargs.setdefault('blank', True)
        #kwargs.setdefault('editable', False)

        populate_from = kwargs.pop('populate_from', None)
        if populate_from is None:
            raise ValueError("missing 'populate_from' argument")
        else:
            self._populate_from = populate_from
        self.separator = kwargs.pop('separator', u'-')
        self.overwrite = kwargs.pop('overwrite', False)
        super(AutoSlugField, self).__init__(*args, **kwargs)

    def _slug_strip(self, value):
        """
        Cleans up a slug by removing slug separator characters that occur at
        the beginning or end of a slug.

        If an alternate separator is used, it will also replace any instances
        of the default '-' separator with the new separator.
        """
        re_sep = '(?:-|%s)' % re.escape(self.separator)
        value = re.sub('%s+' % re_sep, self.separator, value)
        return re.sub(r'^%s+|%s+$' % (re_sep, re_sep), '', value)

    def slugify_func(self, content):
        return slugify(content)

    def create_slug(self, model_instance, document):
        # get fields to populate from and slug field to set
        if not isinstance(self._populate_from, (list, tuple)):
            self._populate_from = (self._populate_from,)
        self._slug = getattr(document, self.name)

        if self._slug is None or self.overwrite:
            # slugify the original field content and set next step to 2
            slug_for_field = lambda field: self.slugify_func(getattr(document, field))
            slug = self.separator.join(map(slug_for_field, self._populate_from))
            next = 2
        else:
            # slug already exists, don't create a new one...return the current slug
            return self._slug

        # strip slug depending on max_length attribute of the slug field
        # and clean-up
        slug_len = self.max_length
        if slug_len:
            slug = slug[:slug_len]
        slug = self._slug_strip(slug)
        original_slug = slug
        # exclude the current model instance from the queryset used in finding
        # the next valid slug
        if document.pk:
	        queryset = model_instance.objects(pk__ne=document.pk)
        else:
            queryset = model_instance.objects()

        # form a kwarg dict used to impliment any unique_together contraints
        kwargs = {}
        #for params in model_instance._meta.unique_together:
        #    if self.attname in params:
        #        for param in params:
        #            kwargs[param] = getattr(model_instance, param, None)
        kwargs[self.name] = slug
        # increases the number while searching for the next valid slug
        # depending on the given slug, clean-up
        while not slug or queryset.clone().filter(**kwargs):
            slug = original_slug
            end = '%s%s' % (self.separator, next)
            end_len = len(end)
            if slug_len and len(slug) + end_len > slug_len:
                slug = slug[:slug_len - end_len]
                slug = self._slug_strip(slug)
            slug = '%s%s' % (slug, end)
            kwargs[self.name] = slug
            next += 1
        return slug

#    def pre_save(self, model_instance, add):
    def pre_save(self, sender, document, **kwargs):
        value = unicode(self.create_slug(sender, document))
        setattr(document, self.db_field, value)
        return value

    def get_internal_type(self):
        return "SlugField"


class CreationDateTimeField(DateTimeField):
    """ CreationDateTimeField

    By default, sets editable=False, blank=True, default=datetime.now
    """

    def __init__(self, *args, **kwargs):
        kwargs.setdefault('default', datetime.datetime.now)
        DateTimeField.__init__(self, *args, **kwargs)

    def get_internal_type(self):
        return "DateTimeField"


class ModificationDateTimeField(CreationDateTimeField):
    """ ModificationDateTimeField

    By default, sets editable=False, blank=True, default=datetime.now

    Sets value to datetime.now() on each save of the model.
    """

    def pre_save(self, sender, document, **kwargs):
        value = datetime.datetime.now()
        setattr(document, self.db_field, value)
        return value

    def get_internal_type(self):
        return "DateTimeField"


class UUIDVersionError(Exception):
    pass


class UUIDField(StringField):
    """ UUIDField

    By default uses UUID version 1 (generate from host ID, sequence number and current time)

    The field support all uuid versions which are natively supported by the uuid python module.
    For more information see: http://docs.python.org/lib/module-uuid.html
    """

    def __init__(self, verbose_name=None, name=None, auto=True, version=1, node=None, clock_seq=None, namespace=None, **kwargs):
        kwargs['max_length'] = 36
        self.auto = auto
        self.version = version
        if version == 1:
            self.node, self.clock_seq = node, clock_seq
        elif version == 3 or version == 5:
            self.namespace, self.name = namespace, name
        StringField.__init__(self, verbose_name, name, **kwargs)

    def get_internal_type(self):
        return StringField.__name__

    def contribute_to_class(self, cls, name):
        if self.primary_key:
            assert not cls._meta.has_auto_field, "A model can't have more than one AutoField: %s %s %s; have %s" % (self, cls, name, cls._meta.auto_field)
            super(UUIDField, self).contribute_to_class(cls, name)
            cls._meta.has_auto_field = True
            cls._meta.auto_field = self
        else:
            super(UUIDField, self).contribute_to_class(cls, name)

    def create_uuid(self):
        if not self.version or self.version == 4:
            return uuid.uuid4()
        elif self.version == 1:
            return uuid.uuid1(self.node, self.clock_seq)
        elif self.version == 2:
            raise UUIDVersionError("UUID version 2 is not supported.")
        elif self.version == 3:
            return uuid.uuid3(self.namespace, self.name)
        elif self.version == 5:
            return uuid.uuid5(self.namespace, self.name)
        else:
            raise UUIDVersionError("UUID version %s is not valid." % self.version)

    def pre_save(self, model_instance, add):
        if self.auto and add:
            value = six.u(self.create_uuid())
            setattr(model_instance, self.attname, value)
            return value
        else:
            value = super(UUIDField, self).pre_save(model_instance, add)
            if self.auto and not value:
                value = six.u(self.create_uuid())
                setattr(model_instance, self.attname, value)
        return value
