from dragon.dtypes_inc cimport *
from dragon.channels cimport *
from dragon.managed_memory cimport *
import dragon.dtypes as dtypes
import dragon.infrastructure.parameters as dparms
import dragon.infrastructure.facts as dfacts
import dragon.globalservices.channel as dgchan
from dragon.localservices.options import ChannelOptions
from dragon.rc import DragonError
import sys

BUF_READ = PyBUF_READ
BUF_WRITE = PyBUF_WRITE
DEFAULT_CLOSE_TIMEOUT = 5
STREAM_CHANNEL_IS_MAIN = 1010

cdef enum:
    C_TRUE = 1
    C_FALSE = 0

cdef timespec_t* _computed_timeout(timeout, timespec_t* time_ptr):

    if timeout is None:
        time_ptr = NULL
    elif isinstance(timeout, int) or isinstance(timeout, float):
        if timeout < 0:
            raise ValueError('Cannot provide timeout < 0.')

        # Anything >= 0 means use that as seconds for timeout.
        time_ptr.tv_sec = int(timeout)
        time_ptr.tv_nsec =  int((timeout - time_ptr.tv_sec)*1000000000)
    else:
        raise ValueError('The timeout value must be a float or int')

    return time_ptr

class DragonFLIError(Exception):
    """
    The DragonFLIError is an exception that can be caught that explicitly targets
    those errors generated by the FLI code. The string associated with the
    exception includes any traceback avaialable from the C level interaction.
    """

    def __init__(self, lib_err, msg):
        cdef char * errstr = dragon_getlasterrstr()

        self.msg = msg
        self.lib_msg = errstr[:].decode('utf-8')
        lib_err_str = dragon_get_rc_string(lib_err)
        self.lib_err = lib_err_str[:].decode('utf-8')
        free(errstr)

    def __str__(self):
        return f"FLI Exception: {self.msg}\n*** Dragon C-level Traceback: ***\n{self.lib_msg}\n*** End C-level Traceback: ***\nDragon Error Code: {self.lib_err}"

class DragonFLITimeoutError(DragonFLIError, TimeoutError):
    pass

class FLIEOT(DragonFLIError, EOFError):
    """
    The FLIEOT Exception is used to indicate the end of stream for an
    FLI conversation. This Exception inherits from EOFError so applications
    using the FLI may choose to catch EOFError instead.
    """
    pass


cdef class FLISendH:
    """
    Sending handle for FLInterfaces. A send handle is needed when sending
    data. Proper use of a send handle includes creating it (which also opens
    it for sending), sending data with one or more to the send operations,
    and closing it once data transmission is complete.
    """

    cdef:
        dragonFLISendHandleDescr_t _sendh
        dragonFLIDescr_t _adapter
        bool _is_open
        object _default_timeout

    def __init__(self, FLInterface adapter, Channel stream_channel=None, timeout=None, use_main_as_stream_channel=False):
        """
        When creating a send handle an application may provide a stream
        channel to be used. If specifying that the main channel is to be
        used as a stream channel then both sender and receiver must agree
        to this. Both send and receive handle would need to be specified
        using the use_main_as_stream_channel in that case.

        :param adapter: An FLI over which to create a send handle.

        :param stream_channel: Default is None. The sender may supply a stream
            channel when opening a send handle. If the FLI is created with
            stream channels, then the value of the argument may be None. If
            supplied by a user then the main channel of the FLI must exist.
            If use_main_as_stream_channel is True, this argument must be
            None.

        :param use_main_as_stream_channel: Default is False. If True, then both
            send handle and receive handle must be true. This would indicate
            that both sender and receiver are agreeing they are the only
            sender and the only receiver and they wish to use the single main
            channel as the stream channel. This can be useful in some
            restricted circumstances but must only be used when there is
            exactly one sender and one receiver on the FLI.

        :param timeout: Default is None. None means to block forever. Otherwise
            the timeout should be some number of seconds to wait for the
            operation to complete. The operation could timeout when not
            supplying a stream channel and there is no channel available
            during the specified amount of time in the manager channel. The timeout
            provided here also becomes the default timeout when used in the context
            manager framework.

        :return: An FLI send handle.
        """
        cdef:
            dragonError_t derr
            dragonChannelDescr_t * c_strm_ch = NULL
            timespec_t timer
            timespec_t* time_ptr

        self._adapter = adapter._adapter
        time_ptr = _computed_timeout(timeout, &timer)

        if stream_channel is not None:
            c_strm_ch = &stream_channel._channel

        if use_main_as_stream_channel:
            c_strm_ch = STREAM_CHANNEL_IS_MAIN_FOR_1_1_CONNECTION

        with nogil:
            derr = dragon_fli_open_send_handle(&self._adapter, &self._sendh, c_strm_ch, time_ptr)

        if derr == DRAGON_TIMEOUT:
            raise DragonFLITimeoutError(derr, "Timed out while opening send handle.")

        if derr != DRAGON_SUCCESS:
            raise DragonFLIError(derr, "Could not open send handle stream.")

        self._is_open = True
        self._default_timeout = timeout

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close(timeout=self._default_timeout)

    def close(self, timeout=None):
        """
        When the conversation is complete the send handle should be closed. In the case of a
        buffered FLI, no data is sent until the send handle is closed. In all cases, closing
        the send handle indicates the end of the stream for the receiver.
        """
        cdef:
            dragonError_t derr
            timespec_t timer
            timespec_t* time_ptr

        if not self._is_open:
            return

        time_ptr = _computed_timeout(timeout, &timer)

        with nogil:
            derr = dragon_fli_close_send_handle(&self._sendh, time_ptr)

        if derr == DRAGON_TIMEOUT:
            raise DragonFLITimeoutError(derr, "Timed out while closing send handle.")

        if derr != DRAGON_SUCCESS:
            raise DragonFLIError(derr, "Could not close send handle stream.")

        self._is_open = False

    def __del__(self):
        try:
            self.close(timeout=DEFAULT_CLOSE_TIMEOUT)
        except:
            pass

    def send_bytes(self, bytes data, uint64_t arg=0, bool buffer=False, timeout=None):
        """
        When sending bytes it is possible to specify the bytes to be sent. In addition,
        you may specify a user specified argument or hint to be sent. If buffer is true, then
        data is not actually sent on this call, but buffered for future call or until the send
        handle is closed.
        """
        cdef:
            dragonError_t derr
            #uint8_t * c_data
            size_t num_bytes
            timespec_t timer
            timespec_t* time_ptr
            int data_len

        if self._is_open == False:
            raise RuntimeError("Handle not open, cannot send data.")

        time_ptr = _computed_timeout(timeout, &timer)

        cdef const unsigned char[:] c_data = data
        data_len = len(data)
        arg_val = arg

        with nogil:
            derr = dragon_fli_send_bytes(&self._sendh, data_len, <uint8_t *>&c_data[0], arg, buffer, time_ptr)

        if derr == DRAGON_TIMEOUT:
            raise DragonFLITimeoutError(derr, "Time out while sending bytes.")

        if derr != DRAGON_SUCCESS:
            raise DragonFLIError(derr, "Failed to send message over stream channel.")


    def send_mem(self, MemoryAlloc mem, uint64_t arg=0, transfer_ownership=True, timeout=None):
        cdef:
            dragonError_t derr
            timespec_t timer
            timespec_t* time_ptr
            bool _transfer


        if self._is_open == False:
            raise RuntimeError("Handle not open, cannot send data.")

        time_ptr = _computed_timeout(timeout, &timer)
        arg_val = arg
        _transfer = transfer_ownership

        with nogil:
            derr = dragon_fli_send_mem(&self._sendh, &mem._mem_descr, arg, _transfer, time_ptr)

        if derr == DRAGON_TIMEOUT:
            raise DragonFLITimeoutError(derr, "Time out while sending memory.")

        if derr != DRAGON_SUCCESS:
            raise DragonFLIError(derr, "Failed to send memory over stream channel.")

    def create_fd(self, bool buffered=False, size_t chunk_size=0, arg=0, timeout=None):
        """
        Opens a writable file-descriptor and returns it.
        """
        cdef:
            dragonError_t derr
            int fdes
            timespec_t timer
            timespec_t* time_ptr
            uint64_t user_arg

        if self._is_open == False:
            raise RuntimeError("Handle not open, cannot get a file descriptor.")

        time_ptr = _computed_timeout(timeout, &timer)
        user_arg = arg

        with nogil:
            derr = dragon_fli_create_writable_fd(&self._sendh, &fdes, buffered, chunk_size, user_arg, time_ptr)

        if derr == DRAGON_TIMEOUT:
            raise DragonFLITimeoutError(derr, "Time out while creating writable file descriptor.")

        if derr != DRAGON_SUCCESS:
            raise DragonFLIError(derr, "Could not open writeable file descriptor.")

        return fdes

    def finalize_fd(self):
        """
        Flushes a file-descriptor and waits until all buffers are written and the
        file descriptor is closed.
        """
        cdef:
            dragonError_t derr

        if self._is_open == False:
            raise RuntimeError("Handle is not open, cannot finalize an fd on a closed send handle.")

        with nogil:
            derr = dragon_fli_finalize_writable_fd(&self._sendh)

        if derr == DRAGON_TIMEOUT:
            raise DragonFLITimeoutError(derr, "Time out while finalizing the writable file descriptor.")

        if derr != DRAGON_SUCCESS:
            raise DragonFLIError(derr, "Could not finalize writable file descriptor")



cdef class FLIRecvH:
    """
    Receiving handle for FLInterfaces.
    """

    cdef:
        dragonFLIRecvHandleDescr_t _recvh
        dragonFLIDescr_t _adapter
        bool _is_open
        object _default_timeout

    def __init__(self, FLInterface adapter, Channel stream_channel=None, timeout=None, use_main_as_stream_channel=False):
        """
        If specifying that the main channel is to be
        used as a stream channel then both sender and receiver must agree
        to this. Both send and receive handle would need to be specified
        using the use_main_as_stream_channel in that case.

        :param adapter: An FLI over which to create a send handle.

        :param stream_channel: Default is None. The receiver may supply a stream
            channel when opening a receive handle. If the FLI is created with
            stream channels, then the value of the argument may be None. If
            supplied by a user then the manager channel of the FLI must exist.
            If use_main_as_stream_channel is True, this argument must be
            None.

        :param use_main_as_stream_channel: Default is False. If True, then both
            send handle and receive handle must be true. This would indicate
            that both sender and receiver are agreeing they are the only
            sender and the only receiver and they wish to use the single main
            channel as the stream channel. This can be useful in some
            restricted circumstances but must only be used when there is
            exactly one sender and one receiver on the FLI.

        :param timeout: Default is None. None means to block forever. Otherwise
            the timeout should be some number of seconds to wait for the
            operation to complete. The operation could timeout when not
            supplying a stream channel and there is no channel available
            during the specified amount of time in the manager channel. The timeout
            provided here also becomes the default timeout when used in the context
            manager framework.

        :return: An FLI send handle.
        """
        cdef:
            dragonError_t derr
            dragonChannelDescr_t * c_strm_ch = NULL
            timespec_t timer
            timespec_t* time_ptr

        # This seems short, might flesh out more later
        self._adapter = adapter._adapter

        time_ptr = _computed_timeout(timeout, &timer)

        if stream_channel is not None:
            c_strm_ch = &stream_channel._channel

        if use_main_as_stream_channel:
            c_strm_ch = STREAM_CHANNEL_IS_MAIN_FOR_1_1_CONNECTION

        with nogil:
            derr = dragon_fli_open_recv_handle(&self._adapter, &self._recvh, c_strm_ch, time_ptr)

        if derr == DRAGON_TIMEOUT:
            raise DragonFLITimeoutError(derr, "Time out while opening receive handle.")

        if derr != DRAGON_SUCCESS:
            raise DragonFLIError(derr, "Could not open receive handle stream")

        self._is_open = True
        self._default_timeout = timeout

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        mem_discarded = 0
        try:
            while not self.stream_received:
                mem = None
                try:
                    mem, hint = self.recv_mem()
                except EOFError:
                    pass

                if mem is not None:
                    mem.free()
                mem_discarded += 1

            self.close(self._default_timeout)
        except Exception as ex:
            try:
                self.close(self._default_timeout)
            except:
                pass
            raise ex

        if mem_discarded > 1:
            raise DragonFLIError(DragonError.INVALID_MESSAGE, 'There was message data discarded while closing the FLI recv handle.')

    def close(self, timeout=None):
        cdef:
            dragonError_t derr
            timespec_t timer
            timespec_t* time_ptr

        if not self._is_open:
            return

        time_ptr = _computed_timeout(timeout, &timer)

        with nogil:
            derr = dragon_fli_close_recv_handle(&self._recvh, time_ptr)

        if derr == DRAGON_TIMEOUT:
            raise DragonFLITimeoutError(derr, "Time out while closing receive handle.")

        if derr != DRAGON_SUCCESS:
            raise DragonFLIError(derr, "Could not close receive handle stream")

        self._is_open = False

    @property
    def stream_received(self):
        cdef:
            dragonError_t derr
            bool result

        derr = dragon_fli_stream_received(&self._recvh, &result)

        if derr != DRAGON_SUCCESS:
            raise DragonFLIError(derr, "Failed to get the stream received property")

        return result

    def __del__(self):
        try:
            self.close(timeout=DEFAULT_CLOSE_TIMEOUT)
        except:
            pass

    def recv_bytes_into(self, unsigned char[::1] bytes_buffer=None, timeout=None):
        cdef:
            uint64_t arg
            size_t max_bytes
            size_t num_bytes
            timespec_t timer
            timespec_t* time_ptr

        if self._is_open == False:
            raise RuntimeError("Handle is not open, cannot receive")

        time_ptr = _computed_timeout(timeout, &timer)

        max_bytes = len(bytes_buffer)

        # This gets a memoryview slice of the buffer
        cdef unsigned char [:] c_data = bytes_buffer
        # To pass in as a pointer, get the address of the 0th index &c_data[0]
        with nogil:
            derr = dragon_fli_recv_bytes_into(&self._recvh, max_bytes, &num_bytes, &c_data[0], &arg, time_ptr)

        if derr == DRAGON_TIMEOUT:
            raise DragonFLITimeoutError(derr, "Time out while receiving bytes into.")

        if derr == DRAGON_EOT:
            raise FLIEOT(derr, "End of Transmission")

        if derr != DRAGON_SUCCESS:
            raise DragonFLIError(derr, "Could not receive into bytes buffer")

        # Landing pad should be populated, just return arg
        return arg

    def recv_bytes(self, size=-1, timeout=None):
        cdef:
            dragonError_t derr
            size_t num_bytes
            size_t max_bytes = 0
            uint8_t * c_data
            uint64_t arg
            timespec_t timer
            timespec_t* time_ptr

        if self._is_open == False:
            raise RuntimeError("Handle is not open, cannot receive")

        time_ptr = _computed_timeout(timeout, &timer)

        if size > 0:
            max_bytes = size

        # A max_bytes value of 0 means "get everything"
        with nogil:
            derr = dragon_fli_recv_bytes(&self._recvh, max_bytes, &num_bytes, &c_data, &arg, time_ptr)

        if derr == DRAGON_TIMEOUT:
            raise DragonFLITimeoutError(derr, "Time out while receiving bytes.")

        if derr == DRAGON_EOT:
            if num_bytes > 0:
                free(c_data)
            raise FLIEOT(derr, "End of Transmission")

        if derr != DRAGON_SUCCESS:
            raise DragonFLIError(derr, "Error receiving FLI data")

        # Convert to a memoryview
        py_view = PyMemoryView_FromMemory(<char *>c_data, num_bytes, BUF_WRITE)
        # Convert memoryview to bytes
        py_bytes = py_view.tobytes()
        # Release underlying malloc now that we have a copy
        free(c_data)
        c_data = NULL
        # Return data and metadata as a tuple
        return (py_bytes, arg)

    def recv_mem(self, timeout=None):
        cdef:
            dragonError_t derr
            dragonMemoryDescr_t mem
            uint64_t arg
            timespec_t timer
            timespec_t* time_ptr

        if self._is_open == False:
            raise RuntimeError("Handle is not open, cannot receive memory object")

        time_ptr = _computed_timeout(timeout, &timer)

        with nogil:
            derr = dragon_fli_recv_mem(&self._recvh, &mem, &arg, time_ptr)

        if derr == DRAGON_TIMEOUT:
            raise DragonFLITimeoutError(derr, "Time out while receiving memory.")

        if derr == DRAGON_EOT:
            with nogil:
                dragon_memory_free(&mem)
            raise FLIEOT(derr, "End of Transmission")

        if derr != DRAGON_SUCCESS:
            raise DragonFLIError(derr, "Error receiving FLI data into memory object")

        mem_obj = MemoryAlloc.cinit(mem)
        return (mem_obj, arg)

    def create_fd(self, timeout=None):
        """
        Creates a readable file-descriptor and returns it.
        """
        cdef:
            dragonError_t derr
            int fdes
            timespec_t timer
            timespec_t* time_ptr

        if self._is_open == False:
            raise RuntimeError("Handle is not open, cannot create a file descriptor on a closed handle.")

        time_ptr = _computed_timeout(timeout, &timer)

        with nogil:
            derr = dragon_fli_create_readable_fd(&self._recvh, &fdes, time_ptr)

        if derr == DRAGON_TIMEOUT:
            raise DragonFLITimeoutError(derr, "Time out while creating readable file descriptor.")

        if derr != DRAGON_SUCCESS:
            raise DragonFLIError(derr, "Could not open readable file descriptor")

        return fdes

    def finalize_fd(self):
        """
        Flushes a file-descriptor and waits until all buffers are read and the
        file descriptor is closed.
        """
        cdef:
            dragonError_t derr

        if self._is_open == False:
            raise RuntimeError("Handle is not open, cannot finalize an fd on a closed receive handle.")

        with nogil:
            derr = dragon_fli_finalize_readable_fd(&self._recvh)

        if derr == DRAGON_TIMEOUT:
            raise DragonFLITimeoutError(derr, "Time out while finalizing the readable file descriptor.")

        if derr != DRAGON_SUCCESS:
            raise DragonFLIError(derr, "Could not finalize readable file descriptor")




cdef class FLInterface:
    """
    Cython wrapper for the File-Like-Interface
    """

    cdef:
        dragonFLIDescr_t _adapter
        dragonFLISerial_t _serial
        bool _is_serialized
        bool _is_buffered
        list stream_channel_list
        MemoryPool pool


    def __getstate__(self):
        return (self.serialize(), self.pool)

    def __setstate__(self, state):
        serial_fli, pool = state
        if pool is None or not pool.is_local:
            pool = None
        self._attach(serial_fli, pool)


    def _attach(self, ser_bytes, MemoryPool pool=None):
        cdef:
            dragonError_t derr
            dragonFLISerial_t _serial
            dragonMemoryPoolDescr_t * mpool = NULL

        if len(ser_bytes) == 0:
            raise DragonFLIError(DragonError.INVALID_ARGUMENT, "The serialized bytes where empty.")

        _serial.len = len(ser_bytes)
        cdef const unsigned char[:] cdata = ser_bytes
        _serial.data = <uint8_t *>&cdata[0]
        self._is_serialized = False
        self.pool = pool

        if pool is not None:
            mpool = &pool._pool_hdl

        derr = dragon_fli_attach(&_serial, mpool, &self._adapter)

        if derr != DRAGON_SUCCESS:
            raise DragonFLIError(derr, "Could not attach to FLI adapter")

        derr = dragon_fli_is_buffered(&self._adapter, &self._is_buffered)

        if derr != DRAGON_SUCCESS:
            raise DragonFLIError(derr, "Failed to get the is buffered property")

        return self

    def __del__(self):
        if self._is_serialized:
            dragon_fli_serial_free(&self._serial)

    def __init__(self, Channel main_ch=None, Channel manager_ch=None, MemoryPool pool=None,
                        stream_channels=[], bool use_buffered_protocol=False):

        cdef:
            dragonError_t derr
            dragonChannelDescr_t ** strm_chs = NULL
            dragonChannelDescr_t * c_main_ch = NULL
            dragonChannelDescr_t * c_mgr_ch = NULL
            dragonMemoryPoolDescr_t * c_pool = NULL
            Channel ch # Necessary to cast python objects into cython objects when pulling out stream_channel values
            dragonULInt num_stream_channels

        self._is_serialized = False
        self.pool = pool

        ###
        ### If creating main and manager channels, make sure their capacity is set to the number of stream channels
        ###

        num_stream_channels = len(stream_channels)
        self._is_buffered = use_buffered_protocol

        if pool is None and main_ch is None:
            # Get default pool muid and create a main_channel from there
            default_muid = dfacts.default_pool_muid_from_index(dparms.this_process.index)
            ch_options = ChannelOptions(capacity=num_stream_channels)
            main_ch = dgchan.create(default_muid, options=ch_options)

        # Get pointers to the handles
        # This simplifies the actual C call since the pointers will either be NULL or assigned to the objects handle
        if main_ch is not None:
            c_main_ch = &main_ch._channel

        if manager_ch is not None:
            c_mgr_ch = &manager_ch._channel

        if pool is not None:
            c_pool = &pool._pool_hdl

        if num_stream_channels > 0:
            strm_chs = <dragonChannelDescr_t **>malloc(sizeof(dragonChannelDescr_t*) * num_stream_channels)
            for i in range(num_stream_channels):
                ch = stream_channels[i]
                strm_chs[i] = &ch._channel

        with nogil:
            derr = dragon_fli_create(&self._adapter, c_main_ch, c_mgr_ch, c_pool,
                                    num_stream_channels, strm_chs, use_buffered_protocol, NULL)

        if strm_chs != NULL:
            free(strm_chs) # Free our Malloc before error checking to prevent memory leaks
            strm_chs = NULL
        if derr != DRAGON_SUCCESS:
            raise DragonFLIError(derr, "Failed to create new FLInterface")

    @classmethod
    def create_buffered(cls, Channel main_ch=None, MemoryPool pool=None):
        """
        Helper function to more easily create a simple buffered FLInterface
        Does not require any internal function, it's simply limiting the number of options for the user
        in order to make it more straightforward to make an explicitly buffered FLI
        """
        return cls(main_ch=main_ch, pool=pool, use_buffered_protocol=True)


    def destroy(self):
        cdef dragonError_t derr

        with nogil:
            derr = dragon_fli_destroy(&self._adapter)

        if derr != DRAGON_SUCCESS:
            raise DragonFLIError(derr, "Failed to destroy FLInterface")

    def num_available_streams(self, timeout=None):
        cdef:
            dragonError_t derr
            uint64_t count
            timespec_t timer
            timespec_t* time_ptr

        time_ptr = _computed_timeout(timeout, &timer)

        with nogil:
            derr = dragon_fli_get_available_streams(&self._adapter, &count, time_ptr)

        if derr == DRAGON_TIMEOUT:
            raise DragonFLITimeoutError(derr, "Time out while getting the number of available streams.")

        if derr != DRAGON_SUCCESS:
            raise DragonFLIError(derr, "Failed to get the available streams")

        return count

    def serialize(self):
        cdef dragonError_t derr

        if not self._is_serialized:
            derr = dragon_fli_serialize(&self._adapter, &self._serial)

            if derr != DRAGON_SUCCESS:
                raise DragonFLIError(derr, "Failed to serialize FLInterface")

            self._is_serialized = True

        py_obj = self._serial.data[:self._serial.len]
        return py_obj

    @classmethod
    def attach(cls, serialized_bytes, mem_pool=None):
        # If mem_pool is None, the default node-local memorypool will be used
        empty_fli = cls.__new__(cls)
        return empty_fli._attach(serialized_bytes, mem_pool)

    def detach(self):
        cdef dragonError_t derr

        derr = dragon_fli_detach(&self._adapter)

        if derr != DRAGON_SUCCESS:
            raise DragonFLIError(derr, "Failed to detach from FLI adapter")

    def sendh(self, *args, **kwargs):
        """
        Return a new FLI Send Handle object
        """
        return FLISendH(self, *args, **kwargs)

    def recvh(self, *args, **kwargs):
        """
        Return a new FLI Recv Handle object
        """
        return FLIRecvH(self, *args, **kwargs)

    @property
    def is_buffered(self):
        return self._is_buffered

