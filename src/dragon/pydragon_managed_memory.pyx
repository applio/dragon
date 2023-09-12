from dragon.dtypes_inc cimport *
import enum

################################
# Begin Cython definitions
################################

# Custom exception classes
# @MCB TODO: Make this a generic base and share between cython layers?
# @MCB TODO: Naming scheme is to prevent confusion with other generic Memory or Pool exceptions, but seems clunky

class DragonMemoryError(Exception):
    """TBD """

    def __init__(self, lib_err, msg):
        cdef char * errstr = dragon_getlasterrstr()

        self.msg = msg
        self.lib_msg = errstr[:].decode('utf-8')
        lib_err_str = dragon_get_rc_string(lib_err)
        self.lib_err = lib_err_str[:].decode('utf-8')
        free(errstr)

    def __str__(self):
        return f"ManagedMemory Exception: {self.msg}\n*** Dragon C-level Traceback: ***\n{self.lib_msg}\n*** End C-level Traceback: ***\nDragon Error Code: {self.lib_err}"

    @enum.unique
    class Errors(enum.Enum):
        SUCCESS = 0
        FAIL = 1

class DragonPoolError(DragonMemoryError):
    """TBD """
    @enum.unique
    class Errors(enum.Enum):
        SUCCESS = 0
        FAIL = 1
        CREATE_FAIL = 2
        ATTACH_FAIL = 3

class DragonPoolCreateFail(DragonPoolError):
    """TBD """
    pass

class DragonPoolAttachFail(DragonPoolError):
    """TBD """
    pass

class DragonPoolDetachFail(DragonPoolError):
    """TBD """
    pass

class DragonPoolAllocationNotAvailable(DragonPoolError):
    """TBD """
    pass

# @MCB TODO: How do we expose ctypedef enums directly to python instead of having to maintain this?
# PJM: there is an easy way to do this (I have it below for the ConnMsgHeader stuff).  We'level
#  do this as part of cleanup.
class PoolType(enum.Enum):
    """TBD """
    SHM = DRAGON_MEMORY_TYPE_SHM
    FILE = DRAGON_MEMORY_TYPE_FILE
    PRIVATE = DRAGON_MEMORY_TYPE_PRIVATE


class AllocType(enum.Enum):
    """TBD """
    DATA = DRAGON_MEMORY_ALLOC_DATA
    CHANNEL = DRAGON_MEMORY_ALLOC_CHANNEL
    CHANNEL_BUFFER = DRAGON_MEMORY_ALLOC_CHANNEL_BUFFER

DRAGON_MEMORY_DEFAULT_TIMEOUT = 300

# PJM: PE-38098 is a place holder for a lot of cleanup in this Filename
# we need to:
# * get rid of the attr class here and absorb it as optional args into create
# * mimic the way the constructors for Channels ard done here
# * LOTS of cleanup on typing of args, having things sit on C calls (not other Pythin classes) for performance
# * fix the exception classes following what we did in Channels
# * carry through all of the available Pool attributes
# * tidy up the enum above and anywhere else

cdef class MemoryPoolAttr:
    """
    Cython wrapper for managed memory attributes
    Currently unused
    """

    cdef dragonMemoryPoolAttr_t _mattr

    def __init__(self, pre_alloc_blocks=None):
        cdef dragonError_t derr

        if pre_alloc_blocks is not None:
            if not isinstance(pre_alloc_blocks, list):
                raise RuntimeError(f"MemoryAttr Error: pre_alloc_blocks must be a list of ints")
            if not all(isinstance(item, int) for item in pre_alloc_blocks):
                raise RuntimeError(f"MemoryAttr Error: pre_alloc_blocks must be a list of ints")

        derr = dragon_memory_attr_init(&self._mattr)
        if derr != DRAGON_SUCCESS:
            raise RuntimeError(f"MemoryAttr Error: Unable to initialize memory attribute. Dragon Error Code: ({derr})")

        if pre_alloc_blocks is not None:
            self._mattr.npre_allocs = len(pre_alloc_blocks)
            self._mattr.pre_allocs = <size_t *>malloc(sizeof(size_t) * self._mattr.npre_allocs)
            for i in range(self._mattr.npre_allocs):
                self._mattr.pre_allocs[i] = pre_alloc_blocks[i]

    def __del__(self):
        cdef dragonError_t derr

        derr = dragon_memory_attr_destroy(&self._mattr)


cdef class MemoryAlloc:
    """
    Cython wrapper object for memory pool allocations.
    """

    def __del__(self):
        if self._is_serial == 1:
            dragon_memory_serial_free(&self._mem_ser)

    def get_memview(self):
        """
        Get a memoryview of the underlying memory

        :return: Memoryview object
        """
        cdef:
            dragonError_t derr
            void * ptr

        derr = dragon_memory_get_pointer(&self._mem_descr, &ptr)
        if derr != DRAGON_SUCCESS:
            raise DragonMemoryError(derr, "Could not get memory pointer")

        # 256 for Read, 512 for Write?
        return PyMemoryView_FromMemory(<char*>ptr, self._mem_size, 512)

    def serialize(self):
        """
        Serialize the memory allocation for storage or communication

        :return: Memoryview of the serialized data
        """
        cdef:
            dragonError_t derr

        derr = dragon_memory_serialize(&self._mem_ser, &self._mem_descr)
        if derr != DRAGON_SUCCESS:
            raise DragonMemoryError(derr, "Could not serialize memory")

        self._is_serial = 1
        return self._mem_ser.data[:self._mem_ser.len]

    def clone(self, offset=0, length=None):
        """
        Clone this memory allocation with an offset into it.

        :param size: offset in bytes into this allocation
        :return: New MemoryAlloc object
        :raises: RuntimeError
        """
        cdef:
            dragonError_t derr
            dragonMemoryDescr_t mem
            size_t custom_length

        if not isinstance(offset, int):
            raise TypeError(f"Allocation offset must be int, got type {type(offset)}")

        if offset < 0:
            raise RuntimeError("Offset cannot be less than 0 for memory allocations")

        if length is not None:
            if not isinstance(length, int):
                raise TypeError(f"Allocation custom length must be int, got type {type(length)}")
            if length < 0:
                raise RuntimeError("Length cannot be less than 0 for memory allocations")

            custom_length = <size_t>length
            derr = dragon_memory_descr_clone(&mem, &self._mem_descr, offset, &custom_length)
        else:
            derr = dragon_memory_descr_clone(&mem, &self._mem_descr, offset, NULL)

        if derr != DRAGON_SUCCESS:
            raise DragonPoolError(derr, "Could not clone allocation")

        mem_alloc_obj = MemoryAlloc.cinit(mem)
        # We had to move the error handling here, in the caller
        if not isinstance(mem_alloc_obj, MemoryAlloc):
            # if there was an error, the returned value is a tuple of the form: (derr, err_str)
            raise DragonMemoryError(mem_alloc_obj[0], mem_alloc_obj[1])
        return mem_alloc_obj

    @classmethod
    def attach(cls, ser_bytes):
        """
        Attach to a serialized memory allocation

        :param ser_bytes: Bytes-like object (memoryview, bytearray, bytes) of a serialized memory descriptor
        :return: MemoryAlloc object
        """
        cdef:
            dragonError_t derr
            dragonMemorySerial_t _ser
            const unsigned char[:] cdata = ser_bytes

        _ser.len = len(ser_bytes)
        _ser.data = <uint8_t*>&cdata[0]

        memobj = MemoryAlloc()

        derr = dragon_memory_attach(&memobj._mem_descr, &_ser)
        if derr != DRAGON_SUCCESS:
            raise DragonMemoryError(derr, "Could not attach to memory")

        derr = dragon_memory_get_size(&memobj._mem_descr, &memobj._mem_size)
        if derr != DRAGON_SUCCESS:
            raise DragonMemoryError(derr, "Could not retrieve memory size")

        memobj._is_attach = 1
        return memobj

    def detach(self):
        """
        Detach from memory previously attached to.
        """
        cdef:
            dragonError_t derr

        # @MCB TODO: Does this still make sense?
        if self._is_attach == 0:
            raise RuntimeError("cannot detach from memory not attached to")

        derr = dragon_memory_detach(&self._mem_descr)
        if derr != DRAGON_SUCCESS:
            raise DragonMemoryError(derr, "could not detach from memory")

        self._is_attach = 0

    def free(self):
        cdef dragonError_t derr

        derr = dragon_memory_free(&self._mem_descr)
        if derr != DRAGON_SUCCESS:
            raise DragonMemoryError(derr, "could not free allocation")

    @property
    def size(self):
        return self._mem_size


cdef class MemoryAllocations:
    """
    Cython wrapper object to provide access to lists of existing memory allocations in a pool
    """

    cdef dragonMemoryPoolAllocations_t allocs

    def __del__(self):
        dragon_memory_pool_allocations_destroy(&self.allocs)

    # @MCB Note: Cython gets really mad if we try to pass in C structs to __cinit__, so this will
    #  do for now
    @staticmethod
    cdef cinit(dragonMemoryPoolAllocations_t allocs):
        """
        Create a MemoryAllocations object and populate its inner C struct.

        :return: MemoryAllocations object
        """
        pyobj = MemoryAllocations()
        pyobj.allocs.nallocs = allocs.nallocs
        pyobj.allocs.types = allocs.types
        pyobj.allocs.ids = allocs.ids
        return pyobj

    @property
    def num_allocs(self):
        """ Number of allocations in pool. """
        return self.allocs.nallocs

    def alloc_type(self, idx):
        """
        Get the type of a particular allocation id.

        :return: Enum of the allocation type (if it exists)
        :raises: RuntimeError if allocation not found
        """
        if idx < 0 or idx >= self.allocs.nallocs:
            raise RuntimeError("Index out of bounds")

        return AllocType(self.allocs.types[idx])

    def alloc_id(self, idx):
        if idx < 0 or idx >= self.allocs.nallocs:
            raise RuntimeError("Index out of bounds")

        return self.allocs.ids[idx]


cdef class MemoryPool:
    """
    Cython wrapper for managed memory pools and related structures
    """

    # @MCB: C attributes and methods are defined in managed_memory.pxd to be shared with other Cython objects
    # This is probably worth revisiting, it feels very clunky.
    #cdef dragonMemoryPoolDescr_t _pool_hdl # Lives in managed_memory.pxd
    #cdef dragonMemoryPoolSerial_t _pool_ser
    #cdef bint _serialized

    def __cinit__(self):
        self._serialized = 0

    def __getstate__(self):
        return (self.serialize(),)

    def __setstate__(self, state):
        (serialized_bytes,) = state
        self.attach(serialized_bytes, existing_memory_pool=self)

    def __del__(self):
        # TODO: Proper error handling for this?
        if self._serialized == 1:
            dragon_memory_pool_serial_free(&self._pool_ser)


    def __init__(self, size, str fname, uid, pre_alloc_blocks=None):
        """
        Create a new memory pool and return a MemoryPool object.

        :param size: Size (in bytes) of the pool.
        :param fname: Filename of the pool to use.
        :param uid: Unique pool identifier to use.
        :param mattr: MemoryPoolAttr object to specify various pool attributes.  *Currently Unused*
        :return: MemoryPool object
        :raises: DragonPoolCreateFail
        """
        cdef:
            dragonError_t derr

        # These are specifically not set with type hints because Cython will automatically
        #   truncate float objects to ints, which allows for things like
        #   mpool = MemoryPool.create(1000.5764, 'foo', 1.5)
        #   which should be considered invalid
        if not isinstance(size, int):
            raise TypeError(f"Pool size must be int, got type {type(size)}")

        if not isinstance(uid, int):
            raise TypeError(f"Pool uid must be int, got type {type(uid)}")

        derr = dragon_memory_attr_init(&self._mattr)
        if derr != DRAGON_SUCCESS:
            raise RuntimeError(f"MemoryAttr Error: Unable to initialized memory attribute. Dragon Error Code: ({derr})")

        # @MCB: if pre_alloc_blocks is used, build mattr struct
        if pre_alloc_blocks is not None:
            if not isinstance(pre_alloc_blocks, list):
                raise RuntimeError(f"MemoryAttr Error: pre_alloc_blocks must be a list of ints")
            if not all(isinstance(item, int) for item in pre_alloc_blocks):
                raise RuntimeError(f"MemoryAttr Error: pre_alloc_blocks must be a list of ints")

            self._mattr.npre_allocs = len(pre_alloc_blocks)
            self._mattr.pre_allocs = <size_t *>malloc(sizeof(size_t) * self._mattr.npre_allocs)
            for i in range(self._mattr.npre_allocs):
                self._mattr.pre_allocs[i] = pre_alloc_blocks[i]

        derr = dragon_memory_pool_create(&self._pool_hdl, size,
                                         fname.encode('utf-8'), uid, &self._mattr)
        # This is purely temporary and gets copied internally on the pool_create call, free it here
        if pre_alloc_blocks is not None:
            free(self._mattr.pre_allocs)
        if derr != DRAGON_SUCCESS:
            raise DragonPoolCreateFail(derr, "Could not create pool")

    @classmethod
    def serialized_uid_fname(cls, pool_ser):
        cdef:
            dragonError_t derr
            dragonULInt uid
            char * fname
            const unsigned char[:] cdata = pool_ser
            dragonMemoryPoolSerial_t _ser

        _ser.len = len(pool_ser)
        _ser.data = <uint8_t*>&cdata[0]
        derr = dragon_memory_pool_get_uid_fname(&_ser, &uid, &fname)
        if derr != DRAGON_SUCCESS:
            raise DragonPoolError(derr, "Error retrieving data from serialized pool data")

        pystring = fname[:].decode('utf-8')
        free(fname)

        return (uid, pystring)


    @classmethod
    def empty_pool(cls):
        return cls.__new__(cls)


    @classmethod
    def attach(cls, pool_ser, *, existing_memory_pool=None):
        """
        Attach to an existing pool through a serialized descriptor.

        :param pool_ser: Bytes-like object of a serialized pool descriptor.
        :return: MemoryPool object
        :raises: DragonPoolAttachFail
        """
        cdef:
            dragonError_t derr
            dragonMemoryPoolSerial_t _ser
            const unsigned char[:] cdata = pool_ser
            MemoryPool mpool

        if existing_memory_pool is None:
            mpool = cls.__new__(cls) # Create an empty instance of MemoryPool
        elif isinstance(existing_memory_pool, MemoryPool):
            mpool = existing_memory_pool
        else:
            raise TypeError(f"Unsupported {type(existing_memory_pool)} != MemoryPool")

        if len(pool_ser) == 0:
            raise ValueError(f'Zero length serialized pool descriptor cannot be attached.')

        _ser.len = len(pool_ser)
        _ser.data = <uint8_t*>&cdata[0]

        derr = dragon_memory_pool_attach(&mpool._pool_hdl, &_ser)
        if derr != DRAGON_SUCCESS:
            raise DragonPoolAttachFail(derr, "Could not attach to serialized pool")

        return mpool

    def destroy(self):
        """
        Destroy the pool created by this object.
        """
        cdef dragonError_t derr

        derr = dragon_memory_pool_destroy(&self._pool_hdl)
        if derr != DRAGON_SUCCESS:
            raise DragonPoolError(derr, "Could not destroy pool")

    def detach(self, serialize=False):
        """
        Detach from a previously attached to pool by this object.

        :param serialize: Boolean to optionally store a serializer before detaching
        """
        cdef dragonError_t derr

        if serialize:
            self.serialize()

        derr = dragon_memory_pool_detach(&self._pool_hdl)
        if derr != DRAGON_SUCCESS:
            DragonPoolAttachFail(derr, "Could not detach pool")

    def serialize(self):
        """
        Serialize the pool held by this object.
        Will store a copy of the serialized data as part of the object after first call.

        :return: Memoryview of serialized pool descriptor.
        """
        cdef:
            dragonError_t derr

        if self._serialized != 1:
            derr = dragon_memory_pool_serialize(&self._pool_ser, &self._pool_hdl)
            if derr != DRAGON_SUCCESS:
                raise DragonPoolError(derr, "Could not serialize pool")

            self._serialized = 1

        # Returns a python copy of the serializer
        return self._pool_ser.data[:self._pool_ser.len]

    # @MCB TODO: Add optional type parameter.  Where should the ID for typed allocs come from?
    def alloc(self, size):
        """
        Allocate a memory block within this pool.
        Please note that the internal memory manager allocates to nearest powers of 2.

        :param size: Size (in bytes) to allocate
        :return: New MemoryAlloc object
        :raises: RuntimeError
        """
        cdef:
            dragonError_t derr
            dragonMemoryDescr_t mem

        if not isinstance(size, int):
            raise TypeError(f"Allocation size must be int, got type {type(size)}")

        # @MCB TODO: What do we want to make the minimum size?
        if size < 1:
            raise RuntimeError("Size cannot be less than 1 for memory allocations")

        derr = dragon_memory_alloc(&mem, &self._pool_hdl, size)

        if derr == DRAGON_DYNHEAP_REQUESTED_SIZE_NOT_AVAILABLE:
            raise DragonPoolAllocationNotAvailable(derr, f"An allocation of size={size} is not available.")

        if derr != DRAGON_SUCCESS:
            raise DragonPoolError(derr, "Could not perform allocation")

        mem_alloc_obj = MemoryAlloc.cinit(mem)
        # We had to move the error handling here, in the caller
        if not isinstance(mem_alloc_obj, MemoryAlloc):
            # if there was an error, the returned value is a tuple of the form: (derr, err_str)
            raise DragonMemoryError(mem_alloc_obj[0], mem_alloc_obj[1])
        return mem_alloc_obj

    def alloc_blocking(self, size, timeout=None):
        """
        Allocate a memory block within this pool.
        Please note that the internal memory manager allocates to nearest powers of 2.

        :param size: Size (in bytes) to allocate
        :return: New MemoryAlloc object
        :raises: RuntimeError
        """
        cdef:
            dragonError_t derr
            dragonMemoryDescr_t mem
            timespec_t timer
            timespec_t* time_ptr
            size_t sz

        if timeout is None:
            time_ptr = NULL
        elif isinstance(timeout, int) or isinstance(timeout, float):
            if timeout < 0:
                raise ValueError('Cannot provide timeout < 0 to alloc_blocking operation')

            # Anything > 0 means use that as seconds for timeout.
            time_ptr = &timer
            timer.tv_sec =  int(timeout)
            timer.tv_nsec = int((timeout - timer.tv_sec)*1000000000)
        else:
            raise ValueError('receive timeout must be a float or int')

        if not isinstance(size, int):
            raise TypeError(f"Allocation size must be int, got type {type(size)}")

        # @MCB TODO: What do we want to make the minimum size?
        if size < 1:
            raise RuntimeError("Size cannot be less than 1 for memory allocations")

        # Assignment causes coercion, not allowed without gil
        sz = size

        with nogil:
            derr = dragon_memory_alloc_blocking(&mem, &self._pool_hdl, sz, time_ptr)

        if derr == DRAGON_TIMEOUT:
            raise TimeoutError("The blocking allocation timed out")

        if derr == DRAGON_DYNHEAP_REQUESTED_SIZE_NOT_AVAILABLE:
            raise DragonPoolAllocationNotAvailable(derr, "A pool allocation of size={size} is not available.")

        if derr != DRAGON_SUCCESS:
            raise DragonPoolError(derr, "Could not perform allocation")

        mem_alloc_obj = MemoryAlloc.cinit(mem)
        # We had to move the error handling here, in the caller
        if not isinstance(mem_alloc_obj, MemoryAlloc):
            # if there was an error, the returned value is a tuple of the form: (derr, err_str)
            raise DragonMemoryError(mem_alloc_obj[0], mem_alloc_obj[1])
        return mem_alloc_obj

    def get_allocations(self):
        """
        Get a list of allocations in this pool

        :return: New MemoryAllocations object
        """
        cdef:
            dragonError_t derr
            dragonMemoryPoolAllocations_t allocs

        derr = dragon_memory_pool_get_allocations(&self._pool_hdl, &allocs)
        if derr != DRAGON_SUCCESS:
            raise DragonPoolError(derr, "Could not retrieve allocation list from pool")

        return MemoryAllocations.cinit(allocs)

    def allocation_exists(self, alloc_type, alloc_id):
        """
        Scan the pool to determine if a given allocation exists

        :param alloc_type: AllocType Enum of the allocation type
        :param alloc_id: Integer ID of the allocation
        :return: True if allocation exists, False otherwise
        """
        cdef:
            dragonError_t derr
            int flag

        derr = dragon_memory_pool_allocation_exists(&self._pool_hdl, alloc_type.value,
                                                    alloc_id, &flag)
        if derr != DRAGON_SUCCESS:
            raise DragonPoolError(derr, "Error checking allocation existence")

        return flag == 1

    def get_alloc_by_id(self, alloc_type, alloc_id):
        """
        Get an allocation object by searching for type and ID

        :param alloc_type: AllocType Enum of the allocation type
        :param alloc_id: Integer ID of the allocation
        :return: New MemoryAlloc object if allocation exists
        :raises: RuntimeError if allocation does not exist
        """
        cdef:
            dragonError_t derr
            dragonMemoryDescr_t mem_descr
            size_t mem_size

        derr = dragon_memory_get_alloc_memdescr(&mem_descr, &self._pool_hdl,
                                                alloc_type.value, alloc_id, 0, NULL)
        if derr != DRAGON_SUCCESS:
            raise DragonPoolError(derr, "Could not retrieve memory descriptor of provided ID and Type")

        derr = dragon_memory_get_size(&mem_descr, &mem_size)
        if derr != DRAGON_SUCCESS:
            raise DragonPoolError(derr, "Could not retrieve size of memory descriptor")

        mem_alloc_obj = MemoryAlloc.cinit(mem_descr)
        # We had to move the error handling here, in the caller
        if not isinstance(mem_alloc_obj, MemoryAlloc):
            # if there was an error, the returned value is a tuple of the form: (derr, err_str)
            raise DragonMemoryError(mem_alloc_obj[0], mem_alloc_obj[1])
        return mem_alloc_obj

    @property
    def is_local(self):
        return dragon_memory_pool_is_local(&self._pool_hdl)

