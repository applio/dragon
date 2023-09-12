"""Dragon's replacement for Multiprocessing's shared ctypes objects: Value and Array.
"""

import dragon
from ..native.lock import Lock
from ..native.value import Value
from ..native.array import Array
from ..globalservices.channel import create, get_refcnt, release_refcnt


def dragon_copy(obj: object) -> object:
    """make a copy of a shared object

    :param obj: original object
    :type obj: obj
    :return: copy of object
    :rtype: obj
    """
    raise NotImplementedError("dragon_copy not implemented yet")


def dragon_synchronized(obj: object, lock=None, ctx=None) -> object:
    """Synchronize an object by wrapping it.

    :param obj: the object to synchronize
    :type obj: object
    :param lock: multiprocessing lock for the synchronized object, defaults to None
    :type lock: multiprocessing.synchronize.Lock, optional
    :param ctx: multiprocessing context to use, defaults to None
    :type ctx: multiprocessing.context.Context, optional
    :return: A synchronized version of the object
    :rtype: object
    """
    raise NotImplementedError("dragon_synchronized not implemented yet")


def RawValue(typecode_or_type, *args, original=None, use_base_impl=True):
    if use_base_impl:
        if original == None:
            raise NameError(f"Dragon patch of Multiprocessing not correct.")
        else:
            return original(typecode_or_type, *args)
    else:
        return DragonRawValue(typecode_or_type, *args)


def RawArray(typecode_or_type, size_or_initializer, original=None, use_base_impl=True):
    if use_base_impl:
        if original == None:
            raise NameError(f"Dragon patch of Multiprocessing not correct.")
        else:
            return original(typecode_or_type, size_or_initializer)
    else:
        return DragonRawArray(typecode_or_type, size_or_initializer)


def Value(typecode_or_type, *args, lock=True, ctx=None, original=None, use_base_impl=False):
    if use_base_impl:
        if original == None:
            raise NameError(f"Dragon patch of Multiprocessing not correct.")
        else:
            return original(typecode_or_type, *args, lock=lock, ctx=ctx)
    else:
        return DragonValue(typecode_or_type, *args, lock=lock, ctx=ctx)


def Array(
    typecode_or_type, size_or_initializer, *args, lock=True, ctx=None, original=None, use_base_impl=False
):
    if use_base_impl:
        if original == None:
            raise NameError(f"Dragon patch of Multiprocessing not correct.")
        else:
            return original(typecode_or_type, size_or_initializer, *args, lock=lock, ctx=ctx)
    else:
        return DragonArray(typecode_or_type, size_or_initializer, *args, lock=lock, ctx=ctx)


class DragonRawValue(dragon.native.value.Value):
    """
    RawValue Class replacement for Value multiprocessing test cases
    """

    def __init__(self, typecode_or_type, value: int = 0, *, ctx: None = None, raw: bool = True):
        """Initialize the mpbridge RawValue object.
        :param typecode_or_type: the typecode or type is returned from the dictionary, typecode_to_type
        :type typecode_or_type: str or ctypes, required
        :param value: the value for the object
        :type value: int, optional
        :param raw: bool, optional
        :type raw: sets whether lock is used or not
        """
        super().__init__(typecode_or_type, value)


class DragonValue(dragon.native.value.Value):
    """
    Value Class replacement
    """

    def __del__(self):
        try:
            cuid = self._channel.cuid
            self._channel.detach()
            release_refcnt(cuid)
        except AttributeError:
            pass

    def __getstate__(self):
        return {
            "base_state": super().__getstate__(),
            "mp_state": (self.get_lock, self.get_obj, self._lock),
        }

    def __setstate__(self, state):
        super().__setstate__(state["base_state"])
        (self.get_lock, self.get_obj, self._lock) = state["mp_state"]

    def __repr__(self):
        return (
            f"Dragon Multiprocessing Value({self._type}, {self.value}, {self._channel.cuid}, {self._muid})"
        )

    def __init__(self, typecode_or_type, value: int = 0, *, ctx: None = None, lock: Lock = True):
        """Initialize the mpbridge value object.
        :param typecode_or_type: the typecode or type is returned from the dictionary, typecode_to_type
        :type typecode_or_type: str or ctypes, required
        :param value: the value for the object
        :type value: int, optional
        :param m_uid: memory pool to create the channel in and message to write value and typecode_or_type in managed memory, defaults to _DEF_MUID
        :type m_uid: int, optional
        :param lock: dragon.native.lock.Lock, optional
        :type lock: creates lock for synchronization for value
        """

        # if lock is False, return the subclass value
        if lock is False:
            super().__init__(typecode_or_type, value)
            return

        elif lock in (True, None) or isinstance(lock, dragon.mpbridge.synchronize.DragonLock):
            # set attributes for lock get_obj and get_lock
            if lock is True:
                lock = Lock(recursive=True)
            self._lock = lock
            super().__init__(typecode_or_type, value)
            self.get_lock = self._get_lock
            self.get_obj = self._type
            return

        # lock is not a valid type
        else:
            raise AttributeError

    def acquire(self):
        return self._lock.acquire()

    def release(self):
        return self._lock.release()

    def _get_lock(self):
        return self._lock

    def __enter__(self):
        self.acquire()

    def __exit__(self, *args):
        self.release()

class DragonRawArray(dragon.native.array.Array):
    """
    RawArray Class replacement for Array multiprocessing test cases
    """

    def __repr__(self):
        return f"{self.__class__.__name__}(typecode_or_type={self._type}, m_uid={self._muid})"

    def __init__(self, typecode_or_type, size_or_initializer, ctx: None = None, raw: bool = True):
        """Initialize the mpbridge RawArray object.
        :param typecode_or_type: the typecode or type is returned from the dictionary, typecode_to_type
        :type typecode_or_type: str or ctypes, required
        :param size_or_initializer: the array for the object
        :type size_or_initializer: range, int, list, required
        :param raw: bool, optional
        :type raw: sets whether lock is used or not
        """
        super().__init__(typecode_or_type, size_or_initializer, lock=False)

class DragonArray(dragon.native.array.Array):
    """
    Array Class replacement
    """

    def __getstate__(self):
        return {
            "base_state": super().__getstate__(),
            "mp_state": (self.get_lock, self.get_obj, self._lock),
        }

    def __setstate__(self, state):
        super().__setstate__(state["base_state"])
        (self.get_lock, self.get_obj, self._lock) = state["mp_state"]

    def __repr__(self):
        return f"{self.__class__.__name__}(typecode_or_type={self._type}, lock={self._lock}, m_uid={self._muid})"

    def __del__(self):
        try:
            cuid = self._channel.cuid
            self._channel.detach()
            release_refcnt(cuid)
        except AttributeError:
            pass

    def __init__(self, typecode_or_type,  size_or_initializer, lock: Lock, ctx: None = None):
        """Initialize the mpbridge array object.

        :param typecode_or_type: the typecode or type is returned from the dictionary, typecode_to_type
        :type typecode_or_type: str or ctypes, required
        :param size_or_initializer: the array for the object
        :type size_or_initializer: range, int, list, required
        :param lock: dragon.native.lock.Lock, optional
        :type lock: creates lock for synchronization for array
        """
        super().__init__(typecode_or_type, size_or_initializer, lock)