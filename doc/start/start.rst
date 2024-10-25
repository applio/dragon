.. _gettingstarted:


Getting Started
+++++++++++++++

Welcome to Dragon!

Dragon is a distributed environment for developing high-performance tools,
libraries, and applications at scale. Here we will walk you through downloading and
installing the Dragon runtime environment and run a first program with it.

Prerequisites
=============

You need to have the following software packages installed on your system:

- Python 3.9, 3.10, or 3.11 corresponding to your whl file (e.g., module load cray-python)
- GCC 9 or later
- Slurm or PBS+PALS (for multi-node Dragon on a super computer) OR
- A cluster with configured passwordless ssh keys and an MPI-like hostfile (to run multi-node
  on a cluster)

Download Dragon
===================

Please go to http://github.com/dragonhpc/dragon to clone or download the distribution.

Install Dragon
===================

Before you can run programs using Dragon, you must set up the run-time for your
environment. The untarred distribution file contains several subdirectories. All
provided commands are relative to the directory that contains the README.md. The
`dragon-*.whl` file must be pip3 installed once for your environment. The
`capnp-*.whl` file is also required. Some setup may be required to use module
support to load module files which set a few environment variables. The steps
are outlined for you in the rest of this section.

You must have Python 3.9 installed and it must be in your path somewhere.

A common choice for running Python programs is to use a Python virtual
environment. An install script is supplied in the distribution that performs the
install step(s) for you and creates and activates a virtual environment. You will
find this install script in the untarred distribution file at the root level.

.. code-block:: console

    . dragon-install

You have completed the prerequisites for running Dragon with multiprocessing programs.

If there was an error about loading modules, then you need to enable module loading. In
that case, see the subsection below on *Enabling Module Support*.

If you have already installed and want to come back and use your install at a later
time you may have to reactivate your environment. Execute this from the same directory.

.. code-block:: console

    . dragon-activate

If you are NOT using a virtual environment then check and possibly update the
`$PATH` so it has the location of pip installed console scripts, such as
~/.local/bin. If using a virtual environment, this step is not necessary.

.. code-block:: console

    export PATH=~/.local/bin:${PATH}

Enabling Module Support
--------------------------

If you intend to use Dragon on your own Linux VM or an image that you personally
installed, you may need to enable module commands first by adding the following
command to your ~/.bashrc or other login script.

.. code-block:: console

    source /usr/share/modules/init/bash

If you use a different shell, look in the `init` directory for a script for your
shell.

Running Dragon
==============

Single-node Dragon
------------------

These set of steps show you how to run a parallel "Hello World" application using
Python multiprocssing with Dragon.

This demo program will print a string of the form `"Hello World from $PROCESSID
with payload=$RUNNING_INT"` using every cpu on your system. So beware if you're
on a supercomputer and in an allocation, your console will be flooded.

Create a file `hello_world.py` containing:

.. code-block:: python
   :linenos:
   :caption: **Hello World in Python multiprocessing with Dragon**

    import dragon
    import multiprocessing as mp
    import time


    def hello(payload):

        p = mp.current_process()

        print(f"Hello World from {p.pid} with payload={payload} ", flush=True)
        time.sleep(1) # force all cpus to show up


    if __name__ == "__main__":

        mp.set_start_method("dragon")

        cpu_count = mp.cpu_count()
        with mp.Pool(cpu_count) as pool:
            result = pool.map(hello, range(cpu_count))

and run it by executing `dragon hello_world.py`. This will result in an output like this:

.. code-block:: console

    dir >$dragon hello_world.py
    Hello World from 4294967302 with payload=0
    Hello World from 4294967301 with payload=1
    Hello World from 4294967303 with payload=2
    Hello World from 4294967300 with payload=3
    +++ head proc exited, code 0


Multi-node Dragon
------------------

This same example can be run across multiple nodes without any modification. The
only requirement is that you have an allocation of nodes (obtained with `salloc`
or `qsub` on a system with the Slurm workload manager) and then execute `dragon`
within that allocation. Dragon will launch across all nodes in the allocation by
default, giving you access to all processor cores on every node. If you don't
have Slurm installed on your system, there are other means of running Dragon
multi-node as well. For more details see :ref:`uguide/running_dragon:Running
Dragon on a Multi-Node System` .


What's Next?
================

Congratulations, you've run your first parallel program with Dragon.

But what have you actually done? Dragon implements Python's standard interface
for parallel programming called `multiprocssing`_ to run a custom function
(`hello`) on a collection of processes using the `Pool` abstraction.
multiprocssing is itself used by many standard Python packages like `Pandas`_,
`Joblib`_ and `NumPy`_. By adding two lines (1 and 16), this program enabled the
Dragon implementation of multiprocessing and made it scale to distributed
supercomputers. If your program uses standard packages like `Pandas`_, these two
lines of code are all that's needed to enable existing libraries that depend on
multiprocssing and your Python multiprocssing programs to run across multiple
nodes and allow them to scale to very large systems.

.. TBD add in some more text about Fortran and C++ once available
* Dragon also includes native objects synchronization and communication objects
  that interoperate across lanaguages including C and Python. Check out the
  :ref:`pguide/pguide:Programming Guide` for :ref:`ref/native/index:Dragon
  Native`.
* Learn by example with Dragon's :ref:`cbook/cbook:Solution Cook Book`.
* Dive into Dragon's details with the :ref:`ref/ref:API Reference`.

.. ------------------------------------------------------------------------
.. External Links
.. _multiprocssing: https://docs.python.org/3/library/multiprocssing.html
.. _Pandas: https://pandas.pydata.org/docs/
.. _JobLib: https://joblib.readthedocs.io/en/latest/
.. _NumPy: https://numpy.org/doc/


