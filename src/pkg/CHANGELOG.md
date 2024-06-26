# Changelog

## [0.9] - 2024-04-22


### Changed

Added lock size into required size of Pool #651 by kent-lee was merged Apr 18, 2024

Update python 3.9 build to sle15sp3 #654 by nicholas-hill was merged Apr 18, 2024 

Efficient GS->LS Group Creation of processes #641 by eric-cozzi was merged Apr 11, 2024

Overhaul of ProcessGroup for improved scalability and reliability [#653, #647 #625] by nicholas-hill was merged Apr 18, 2024; Apr 15, 2024; Mar 25, 2024


### Added

Add signal handling for clean up when workload manager experiences allocation timeout #650 by wahlc was merged Apr 18, 2024

New Distributed Dictionary and Checkpointing Design [#644, #629] by kent-lee was merged Apr 18, 2024, Apr 3, 2024

Update Release Tests #639 by veena-venkata-ghorakavi was merged Apr 5, 2024

On node gpu framework and init #633 by nick-radcliffe was merged Apr 9, 2024

Add hints to transport payloads #630 by nick-radcliffe was merged Mar 27, 2024

Expose policy for process placement #628 by wahlc was merged Mar 26, 2024

### Removed

Limit docs update to one build of master #623 by mohammad-hadi was merged Mar 15, 2024

### Fixed

Fix bad bcast tree init regression brought out by resiliency changes. #645 by nicholas-hill was merged Apr 15, 2024

Fix bad frontend host ID assignment #652 by nicholas-hill was merged Apr 17, 2024

Ensure clean build script does a thorough clean and build #643 by kent-lee was merged Apr 9, 2024

Fix regression and add test for launching pool of pools #638 by wahlc was merged Apr 12, 2024

Fix capnproto build and install #631 by kent-lee was closed Mar 21, 2024

Remove HSTA from bring-up if there's only one backend node #632 by nick-radcliffe was merged Mar 25, 2024

## [0.8] - 2024-02-26


### Changed

### Added

Libfabric support for hsta and multi-NIC support [#620, #614, #594] by nick-radcliffe was merged Mar 7, 2024, Feb 22, 2024, Feb 15, 2024 

PyTorch Dataloader process placement patch and example [#610, #608, #601, #599] by veena-venkata-ghorakavi and wahlc was merged Feb 9, 2024, Feb 6, 2024, Jan 4, 2024  

Streamline node updates [#607] by eric-cozzi was merged Feb 8, 2024 

Build multiple python versions of dragon [#600] by mohammad-hadi was merged Jan 4, 2024

Add Overlay Network docs [#595] by eric-cozzi was merged Jan 2, 2024

Startup time improvement [#586] by eric-cozzi was closed on Nov 29, 2023

Channels file-like interface [#585] by kent-lee was merged 10 days ago

### Removed

Remove devcontainer code-server from the dragon-cleanup script [#606] by nicholas-hill was merged Feb 7, 2024

Remove compressed json wrapper [#596] by eric-cozzi was merged Jan 4, 2024

Remove signal handling and update Slurm srun command [#584] by eric-cozzi was merged on Nov 27, 2023

### Fixed

Fix PMI issues on PBSPro+PALS systems [#617] by nicholas-hill was merged Feb 23, 2024

Add typecast to parameter args if env. var. is empty string [#615] by nicholas-hill was merged Feb 16, 2024

Fix queue `__del__` error from pi demo [#605] by yian-chen was merged Jan 29, 2024

Add checks that only the Primary Launcher Backend talks to GS [#604] by eric-cozzi was merged Jan 30, 2024 • Approved

Fix Pool Detach/Destroy [#598] by kent-lee was merged Jan 4, 2024

Fix mp unittests test.support import compatibility with Python 3.10 and 3.11 [#597] by wahlc was merged Jan 4, 2024

Fix multinode sequence diagrams [#592] by eric-cozzi was merged on Dec 8, 2023

Catch executables with Path-like paths and ensure they are strings [#591] by wahlc was merged on Dec 8, 2023

Raise abnormal exit if head process start fails [#590] by eric-cozzi was merged on Dec 11, 2023

Make device_list in AcceleratorDescriptor serializable for messages [#589] by nicholas-hill was merged on Dec 4, 2023

Log text of SHFwdOutput messages on both backend and frontend [#588] by eric-cozzi was merged on Dec 11, 2023

Remove find_accelerators from `NodeDescriptor.__init__` [#587] by nicholas-hill was merged on Nov 30, 2023

Fix ImportError for mp unittests when tested with Python 3.10+ [#583] by wahlc was merged on Dec 8, 2023

Fix network-config-helper to wait for signal to exit [#582] by eric-cozzi was merged on Nov 22, 2023

Launcher ON should use a different port [#581] by eric-cozzi was merged on Nov 22, 2023

Fix attrs version constraint [#579] by eric-cozzi was merged on Nov 16, 2023

Gateway per msg type [#578] by nick-radcliffe was merged on Nov 21, 2023
