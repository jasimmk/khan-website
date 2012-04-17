# the following 3 imports are needed for blobcache
from __future__ import with_statement

import datetime
import logging
import pickle
import zlib
import os

from google.appengine.api import memcache
from google.appengine.ext import db
from google.appengine.runtime.apiproxy_errors import RequestTooLargeError
from google.appengine.api.datastore_errors import BadRequestError
                                            
from app import App
import request_cache

if App.is_dev_server:
    # cachepy disables itself during development presumably to avoid confusion.
    # Instead, alias it to request_cache. This means individual requests will
    # behave more like production, but the cache will be flushed after a request.
    import request_cache as cachepy
else:
    import cachepy

# layer_cache provides an easy way to cache the result of functions across requests.
# layer_cache uses cachepy's in-memory storage, memcache, and the datastore.
#
# Unless otherwise specified, memcache and in-memory storage are used.
# The datastore layer must be explicitly requested.
#
# When using layer_cache, you can specify which layers to make use of depending 
# on your individual use and the need for speed and memory.
#
# _____Guidelines for which layers to use:_____
#
# a) Is it something that is not-user-specific, used on almost every single 
# request, and won't cause memory errors if it goes InAppMemory? 
# If so, InAppMemory
#
# b) Is it something that is not-user-specific and accessed frequently across 
# all users but doesn't match a)? Definitely memcache
#
# c) Is it something that is user specific, going to be accessed frequently, 
# and absolutely needs to be as fast as possible? Try memcache <--- this one 
# could be a mistake. It is uncertain how much our memcache perf is affected by 
# this, but it's what we're doing now.
#
# d) Is it user-specific and doesn't need to be super blazing fast? Datastore
#
# When considering multiple layers: something that qualifies for a) almost 
# certainly also qualifies for memcache (and maybe datastore if we *really* 
# don't want to run the original function)
# _____Explanation by examples:_____
#
# Cache in both memcache and cachepy the result of
# this long-running function using a static key,
# and return the result when available instead of recalculating:
#
# import layer_cache
#
# @layer_cache.cache()
# def calculate_user_averages():
#    ...do lots of long-running work...
#    return result_for_cache
#
#
# and with expiration every minute:
#
# @layer_cache.cache(expiration=60)
# def calculate_user_averages():
#    ...do lots of long-running work...
#    return result_for_cache
#
# Cache using key generated by utility function that
# varies the key based on the function's input parameters:
#
# @layer_cache.cache_with_key_fxn(lambda object: "layer_cache_key_for_object_%s" % object.id())
# def calculate_object_average(object):
#   ... do lots of long-running work...
#   return result_for_cache
#
# _____Manually busting the cache:_____
#
# When you call your cached function, just pass a special "bust_cache"
# named parameter to ignore any existing cached values and replace
# with whatever is newly returned:
#
# calculate_object_average(object, bust_cache=True)
#
# _____Other settings/options:_____
#
# Only cache in datastore:
# @layer_cache.cache(... layer=layer_cache.Layers.Datastore)
#
# Only cache in memcache:
# @layer_cache.cache(... layer=layer_cache.Layers.Memcache)
#
# Only cache in cachepy's in-app memory cache:
# @layer_cache.cache(... layer=layer_cache.Layers.InAppMemory)
#
# Only cache in memcache and datastore:
# @layer_cache.cache(... layer=layer_cache.Layers.Memcache | layer_cache.Layers.Datastore)
#
# Persist the cached values across different uploaded app verions (disabled by default):
# @layer_cache.cache(... persist_across_app_versions=True)
#
# If key has expired or is no longer in the current cache and throws an error 
# when trying to be recomputed, then try getting resource from permanent key 
# that is not set to expire
# @layer_cache.cache(... expiration=60, permanent_cache_key = 
#   lambda object: "permanent_layer_cache_key_for_object_%s" % object.id())
#
# If you know that a function will always return something bigger than 1MB, you 
# can set this parameter to not bother attempting to set it normally as you know
# it will fail, hence will save 1RPC:
# @layer_cache.cache(... use_chunks=True)
#
# If you know a function will return something that is > 1MB and won't compress
# easily to something much smaller, you can set this value to False to save on
# compression and decompression time 
# @layer_cache.cache(... compress_chunks=False)
#
# _____Disabling:_____
#
# You can disable layer_cache for the rest of the request by calling:
# layer_cache.disable()
# 
# Re-enable it with
# layer_cache.enable()

# 100000 is max for both datastore and memcache - ChunkedResult overhead
MAX_SIZE_OF_CACHE_CHUNKS = 999900

# memcache has 32MB limit for set_multi (this is 32MB - ChunkedResult overhead)
MAX_SIZE = 33300000 

# a random string of this length is prepended to each chunk for values that 
# need to be chunked
CHUNK_GENERATION_LENGTH = 16

# Expire after 25 days by default
DEFAULT_LAYER_CACHE_EXPIRATION_SECONDS = 60 * 60 * 24 * 25 

class Layers:
    Datastore = 1
    Memcache = 2
    InAppMemory = 4

def disable():
    request_cache.set("layer_cache_disabled", True)

def enable():
    request_cache.set("layer_cache_disabled", False)

def is_disabled():
    return request_cache.get("layer_cache_disabled") or False

def cache(
        expiration = DEFAULT_LAYER_CACHE_EXPIRATION_SECONDS,
        layer = Layers.Memcache | Layers.InAppMemory,
        persist_across_app_versions = False,
        use_chunks = False,
        compress_chunks = True):
    def decorator(target):
        key = "__layer_cache_%s.%s__" % (target.__module__, target.__name__)
        def wrapper(*args, **kwargs):
            return layer_cache_check_set_return(target, 
                lambda *args, **kwargs: key, expiration, layer,
                    persist_across_app_versions, None, use_chunks, 
                    compress_chunks, *args, **kwargs)
        return wrapper
    return decorator

def cache_with_key_fxn(
        key_fxn,
        expiration = DEFAULT_LAYER_CACHE_EXPIRATION_SECONDS,
        layer = Layers.Memcache | Layers.InAppMemory,
        persist_across_app_versions = False,
        permanent_key_fxn = None,
        use_chunks = False,
        compress_chunks = True):
    def decorator(target):
        def wrapper(*args, **kwargs):
            return layer_cache_check_set_return(target, key_fxn, expiration, 
                layer, persist_across_app_versions, permanent_key_fxn, 
                use_chunks, compress_chunks, *args, **kwargs)
        return wrapper
    return decorator

def layer_cache_check_set_return(
        target,
        key_fxn,
        expiration = DEFAULT_LAYER_CACHE_EXPIRATION_SECONDS,
        layer = Layers.Memcache | Layers.InAppMemory,
        persist_across_app_versions = False,
        permanent_key_fxn = None,
        use_chunks = False,
        compress_chunks = True,
        *args,
        **kwargs):

    def get_cached_result(key, namespace, expiration, layer):

        if layer & Layers.InAppMemory:
            result = cachepy.get(key)
            if result is not None:
                return result

        if layer & Layers.Memcache:
            maybe_chunked_result = memcache.get(key, namespace=namespace)
            if maybe_chunked_result is not None:
                if isinstance(maybe_chunked_result, ChunkedResult):
                    result = maybe_chunked_result.get_result(memcache, 
                                                            namespace=namespace)
                else:
                    result = maybe_chunked_result

                # Found in memcache, fill upward layers
                if layer & Layers.InAppMemory:
                    cachepy.set(key, result, expiry=expiration)

                return result

        if layer & Layers.Datastore:
            maybe_chunked_result = KeyValueCache.get(key, namespace=namespace)
            if maybe_chunked_result is not None:
                # Found in datastore. Unchunk results if needed, and fill upward 
                # layers
                if isinstance(maybe_chunked_result, ChunkedResult):
                    result = maybe_chunked_result.get_result(KeyValueCache, 
                                                            namespace=namespace)
                    
                    if layer & Layers.Memcache:
                        # Since the result in the datastore needed to be chunked
                        # we will need to use ChunkedResult for memcache as well
                        ChunkedResult.set(key, result, expiration, namespace, 
                                          cache_class=memcache)
                else:
                    result = maybe_chunked_result
                    if layer & Layers.Memcache:
                        # Since the datastore wasn't using a chunked result
                        # This memcache.set should succeed as well.
                        memcache.set(key, result, time=expiration, 
                                     namespace=namespace)

                if layer & Layers.InAppMemory:
                    cachepy.set(key, result, expiry=expiration)
                
                return result
        
    def set_cached_result(key, namespace, expiration, layer, result, 
                          use_chunks, compress_chunks):
        # Cache the result
        if layer & Layers.InAppMemory:
            cachepy.set(key, result, expiry=expiration)

        if layer & Layers.Memcache:
            
            if not use_chunks:

                try:
                    if not memcache.set(key, result, time=expiration, 
                                        namespace=namespace):
                        logging.error("Memcache set failed for %s" % key)
                except ValueError, e:
                    if str(e).startswith("Values may not be more than"):
                        # The result was too big to store in memcache.  Going  
                        # to chunk it and try again
                        ChunkedResult.set(key, result, expiration, namespace, 
                                          compress=compress_chunks,
                                          cache_class=memcache)
                    else: 
                        raise

            else:
                # use_chunks parameter was explicitly set, not going to even 
                # bother trying to put it in memcache directly
                ChunkedResult.set(key, result, expiration, namespace, 
                                  compress=compress_chunks,
                                  cache_class=memcache)
            
        if layer & Layers.Datastore:
            if not use_chunks:
                try:
                    KeyValueCache.set(key, result, time=expiration, 
                                      namespace=namespace)
                except (RequestTooLargeError, BadRequestError), e:
                    if (isinstance(e, RequestTooLargeError) or 
                        str(e).startswith("string property value is too long")):

                        # The result was too big to store in datastore. Going to  
                        # chunk it and try again
                        ChunkedResult.set(key, result, time=expiration, 
                                          namespace=namespace,
                                          compress=compress_chunks, 
                                          cache_class=KeyValueCache)  
                    else:
                        raise
            else:
                # use_chunks parameter was explicitly set, not going to even 
                # bother trying to put it in KeyValueCache directly
                ChunkedResult.set(key, result, time=expiration, 
                                  namespace=namespace,
                                  compress=compress_chunks, 
                                  cache_class=KeyValueCache)
                          

    bust_cache = False
    if "bust_cache" in kwargs:
        bust_cache = kwargs["bust_cache"]
        # delete from kwargs so it's not passed to the target
        del kwargs["bust_cache"]

    key = key_fxn(*args, **kwargs)

    # if key is None, or layer_cache is disabled don't bother trying to get it 
    # from the cache, just execute the function and return it
    if key is None or request_cache.get("layer_cache_disabled"):
        return target(*args, **kwargs)

    namespace = App.version

    if persist_across_app_versions:
        namespace = None

    if not bust_cache:

        result = get_cached_result(key, namespace, expiration, layer)
        if result is not None:
            return result

    try:
        result = target(*args, **kwargs)

    # an error happened trying to recompute the result, see if there is a value for it in the permanent cache
    except Exception, e:
        if permanent_key_fxn is not None:
            permanent_key = permanent_key_fxn(*args, **kwargs)

            result = get_cached_result(permanent_key, namespace, expiration, layer)

            if result is not None:
                logging.info("resource is not available, restoring from permanent cache")

                # In case the key's value has been changed by target's execution
                key = key_fxn(*args, **kwargs)

                #retreived item from permanent cache - save it to the more temporary cache and then return it
                set_cached_result(key, namespace, expiration, layer, result, 
                                  use_chunks, compress_chunks)
                return result

        # could not retrieve item from a permanent cache, raise the error on up
        logging.exception(e)
        raise

    if isinstance(result, UncachedResult):
        # Don't cache this result, just return it
        result = result.result
    else:
        if permanent_key_fxn is not None:
            permanent_key = permanent_key_fxn(*args, **kwargs)
            set_cached_result(permanent_key, namespace, 0, layer, result, 
                              use_chunks, compress_chunks)

        # In case the key's value has been changed by target's execution
        key = key_fxn(*args, **kwargs)
        set_cached_result(key, namespace, expiration, layer, result, 
                          use_chunks, compress_chunks)

    return result

class ChunkedResult():
    ''' Allows for storing of data between 1MB and 32MB in size.  If compression
    is turned on then it will first compress the result and store it in this 
    object with data set, if it is now under 1MB, otherwise if after compression
    or if compression is turned off it will do a set_multi to store the result 
    in chunks.
    '''

    def __init__(self, 
                 chunk_list=None, 
                 generation=None, 
                 data=None, 
                 compress=True):
        ''' Stores info on the data to be stored. Either chunk_list+generation 
        or data is set, but not both

        Arguments:
            chunk_list: listing out the keys of the chunks that store the data 
            generation: a random string that gets prepend to all chunks to make
                        sure that they are all from the same set
            data:  for the case in which the compressed value could fit in a 
                   single chunk, then data will store the compressed result
            compress: boolean saying whether we should compress the result
                      before storing and decompressing afterwards  
        '''
        assert (bool(chunk_list and generation) ^ bool(data)), ("Either " 
                "chunk_list+generation or data must be set, but not both")
        if chunk_list:
            self.chunk_list = chunk_list
            self.generation = generation
        else: 
            self.data = data
        self.compress = compress
        
    @staticmethod
    def set(key, value, time=None, namespace="", cache_class=memcache, 
            compress=True):
        ''' This function will pickle and perhaps compress value, before then
        breaking it up into 1MB chunks and storing it with set_multi to whatever
        class cache_class is set to (memcache or KeyValueCache)
        '''

        result = pickle.dumps(value, pickle.HIGHEST_PROTOCOL)
        if compress:
            result = zlib.compress(result)
        
        size = len(result)
        if size > MAX_SIZE:
            logging.warning("Not caching %s: %i is greater than maxsize %i" % 
                            (key, size, MAX_SIZE))
            return
            
        # if now that we have compressed the item it can fit within a single
        # 1MB object don't use the chunk_list, and it will save us from having
        # to do an extra round-trip on the gets
        if size < MAX_SIZE_OF_CACHE_CHUNKS:
            return cache_class.set(key, 
                                   ChunkedResult(data=result, 
                                                 compress=compress),
                                   time=time,
                                   namespace=namespace)              
                                    
        mapping = {}
        chunk_list = []
        generation = os.urandom(CHUNK_GENERATION_LENGTH) 
        for i, pos in enumerate(range(0, size, MAX_SIZE_OF_CACHE_CHUNKS)):
            chunk = generation + result[pos : pos + MAX_SIZE_OF_CACHE_CHUNKS]                           
            chunk_key = key + "__chunk%i__" % i
            mapping[chunk_key] = chunk
            chunk_list.append(chunk_key)

        mapping[key] = ChunkedResult(chunk_list=chunk_list, 
                                     generation= generation, 
                                     compress=compress)
        
        # Note: set_multi is not atomic so when we get we will need to make sure 
        # that all the keys are there and are part of the same set_multi 
        # operation
        return cache_class.set_multi(mapping, time=time, namespace=namespace)
    
    @staticmethod
    def delete(key, namespace="", cache_class=memcache):
        '''This function will first get the key.  If it is a ChunkedResult and
        has an chunk_list, then it will delete_multi on all the items in that
        list otherwise it will just delete the key'''
        value = cache_class.get(key, namespace)
        if isinstance(value, ChunkedResult) and hasattr(value, "chunk_list"):
            keys = value.chunk_list
            keys.append(key)
            cache_class.delete_multi(keys, namespace=namespace)
        elif value is not None:
            cache_class.delete(key, namespace=namespace)

    def get_result(self, cache_class=memcache, namespace=""):
        '''If the results are stored within this ChunkedResult object it will 
        decompress, depickle and return it.  Otherwise it calls get_multi on the
        cache_class for all items in its chunk_list, combines them together and
        returns the descompressed and depickled result
        '''
        if hasattr(self, "chunk_list"):
            chunked_results = cache_class.get_multi(self.chunk_list, 
                                                    namespace=namespace)
            self.data = ""
            for chunk_key in self.chunk_list:
                if chunk_key not in chunked_results:
                    # if a chunk is missing then it is impossible to depickle
                    # so target func will need to be re-executed
                    return None

                # It is possible that the results come some from a new value of
                # a cached item and some from an old version of the cached item
                # as set_multi is not atomic.  By adding a random generation 
                # string to the beginning of each chunk we can be sure they are 
                # all part of the same set, by checking if that string matches
                # the one in the index
                chunk_result = chunked_results[chunk_key]
                chunk_generation = chunk_result[:CHUNK_GENERATION_LENGTH]
                if chunk_generation != self.generation:
                    logging.warning("invalid chunk: wrong generation string" 
                                    " in chunk %s" % chunk_key)
                    return None

                self.data += chunk_result[CHUNK_GENERATION_LENGTH:]          
            
        if self.compress:
            try:
                self.data = zlib.decompress(self.data)
            except zlib.error:
                # If for some reason the data coming back is corrupted so it 
                # can't be decompressed, we return None in order to recaclulate 
                # the target function
                logging.warning("could not decompress ChunkedResult from cache")
                return None
             
        try:
            return pickle.loads(self.data)
        except Exception:
            # If for some reason the data coming back is corrupted so it can't
            # be depickled, we will return None in order to recaclulate the 
            # target function
            logging.warning("could not depickle ChunkedResult from cache")
            return None
        

# Functions can return an UncachedResult-wrapped object
# to tell layer_cache to skip caching this specific result.
#
# Example:
#
# @layer_cache.cache()
# def slow_and_dangerous():
#   try:
#       return SomethingDangerous()
#   catch:
#       return UncachedResult(SomethingSafe())
#
class UncachedResult():
    def __init__(self, result):
        self.result = result

class KeyValueCache(db.Model):

    value = db.BlobProperty()
    created = db.DateTimeProperty()
    expires = db.DateTimeProperty()
    pickled = db.BooleanProperty(indexed=False)

    def is_expired(self):
        return datetime.datetime.now() > self.expires

    @staticmethod
    def get_namespaced_key(key, namespace=""):
        return "%s:%s" % (namespace, key)

    @staticmethod
    def get_namespaced_keys(keys, namespace=""):
        return [KeyValueCache.get_namespaced_key(key, namespace) 
                for key in keys]

    @staticmethod
    def get(key, namespace=""):
        values = KeyValueCache.get_multi([key], namespace)
        return values.get(key, None)

    @staticmethod
    def get_multi(keys, namespace=""):
        ''' gets multiple KeyValueCache entries at once. It mirrors the 
        parameters of memcache.get_multi and its return values (ie. it will 
        return a dict of the original non-namepsaced keys to their values)
        '''

        namespaced_keys = KeyValueCache.get_namespaced_keys(keys, namespace)

        key_values = KeyValueCache.get_by_key_name(namespaced_keys)
        
        values = {}
        for (key, key_value) in zip(keys, key_values):
            if key_value and not key_value.is_expired():
                # legacy entries in key_value cache that were set with 
                # persist_across_app_versions=True might still be around with
                # .pickled=None.  Once we are sure they are all expired we can
                # delete the "or key_value.pickled is None:"
                # TODO(james): After May 2nd 2012 the default cache time of 25 
                # days should have ended and the or can be removed.
                if key_value.pickled or key_value.pickled is None:
                    values[key] = pickle.loads(key_value.value)
                else:
                    values[key] = key_value.value

        return values

    @staticmethod
    def set(key, value, time=DEFAULT_LAYER_CACHE_EXPIRATION_SECONDS, namespace=""):
        KeyValueCache.set_multi({ key: value }, time=time, 
                                namespace=namespace)
        
    @staticmethod
    def set_multi(mapping, 
                  time=DEFAULT_LAYER_CACHE_EXPIRATION_SECONDS, 
                  namespace=""):                        
        ''' sets multiple KeyValueCache entries at once. It mirrors the 
        parameters of memcache.set_multi. Note: set_multi is not atomic      
        '''
        
        namespaced_mapping = dict(
            (KeyValueCache.get_namespaced_key(key, namespace), value) 
            for key, value in mapping.iteritems())

        dt = datetime.datetime.now()

        dt_expires = datetime.datetime.max
        if time > 0:
            dt_expires = dt + datetime.timedelta(seconds=time)

        key_values = []
        
        for namespaced_key, value in namespaced_mapping.iteritems():    
            
            # check to see if we need to pickle the results
            pickled = False
            if not isinstance(value, str):
                pickled = True
                value = pickle.dumps(value, pickle.HIGHEST_PROTOCOL)

            key_values.append(KeyValueCache(
                    key_name = namespaced_key,
                    value = value,
                    created = dt,
                    expires = dt_expires,
                    pickled = pickled))
        
        db.put(key_values)

    @staticmethod
    def delete(key, namespace=""):
        KeyValueCache.delete_multi([key], namespace)

    @staticmethod
    def delete_multi(keys, namespace=""):
        ''' deletes multiple KeyValueCache entries at once. It mirrors the 
        parameters of memcache.delete_multi
        '''

        namespaced_keys = KeyValueCache.get_namespaced_keys(keys, namespace)
        
        key_values = KeyValueCache.get_by_key_name(namespaced_keys)
        found_key_values = [v for v in key_values if v]
        db.delete(found_key_values)


