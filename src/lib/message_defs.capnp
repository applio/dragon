@0x89c9f71b7b1aa97e; # unique file ID, generated by `capnp id`

struct SHCreateProcessLocalChannelDef {
    puid @0: UInt64;
    respFLI @1: Text;
}

struct SHCreateProcessLocalChannelResponseDef {
    serChannel @0: Text;
}

struct SHSetKVDef {
    key @0: Text;
    value @1: Text;
    respFLI @2: Text;
}

struct SHGetKVDef {
    key @0: Text;
    respFLI @1: Text;
}

struct SHGetKVLResponseDef {
    values @0: List(Text);
}

struct SHGetKVResponseDef {
    value @0: Text;
}

struct DDCreateDef {
    respFLI @0: Text;
    args @1: Text;
}

struct DDRegisterManagerDef {
    mainFLI @0: Text;
    respFLI @1: Text;
    hostID @2: UInt64;
}

struct DDRegisterManagerResponseDef {
    managerID @0: UInt64;
    managers @1: List(Text);
    managerNodes @2: List(Text);
}

struct DDGetRandomManagerDef {
    respFLI @0: Text;
}

struct DDGetRandomManagerResponseDef {
    manager @0: Text;
}

struct DDRegisterClientDef {
    respFLI @0: Text;
    bufferedRespFLI @1: Text;
}

struct DDRegisterClientResponseDef {
    clientID @0: UInt64;
    numManagers @1: UInt64;
    managerID @2: UInt64;
    managerNodes @3: List(Text);
    timeout @4: UInt64;
}

struct DDConnectToManagerDef {
    clientID @0: UInt64;
    managerID @1: UInt64;
}

struct DDConnectToManagerResponseDef {
    manager @0: Text;
}

struct DDRegisterClientIDDef {
    clientID @0: UInt64;
    respFLI @1: Text;
    bufferedRespFLI @2: Text;
}

struct DDDestroyDef {
    clientID @0: UInt64;
    respFLI @1: Text;
}

struct DDDestroyManagerDef {
    respFLI @0: Text;
}

struct DDPutDef {
    clientID @0: UInt64;
    chkptID @1: UInt64;
    persist @2: Bool;
}

struct DDGetDef {
    clientID @0: UInt64;
    chkptID @1: UInt64;
}

struct DDPopDef {
    clientID @0: UInt64;
    chkptID @1: UInt64;
}

struct DDContainsDef {
    clientID @0: UInt64;
    chkptID @1: UInt64;
}

struct DDGetLengthDef {
    clientID @0: UInt64;
    chkptID @1: UInt64;
    respFLI @2: Text;
}

struct DDGetLengthResponseDef {
    length @0: UInt64;
}

struct DDClearDef {
    clientID @0: UInt64;
    chkptID @1: UInt64;
    respFLI @2: Text;
}

struct DDManagerGetNewestChkptID {
    respFLI @0: Text;
}

struct DDManagerGetNewestChkptIDResponse {
    managerID @0: UInt64;
    chkptID @1: UInt64;
}

struct DDManagerStatsDef {
    respFLI @0: Text;
}

struct DDManagerStatsResponseDef {
    data @0: Text;
}

struct DDGetIteratorDef {
    clientID @0: UInt64;
    chkptID @1: UInt64;
}

struct DDGetIteratorResponseDef {
    iterID @0: UInt64;
}

struct DDIteratorNextDef {
    clientID @0: UInt64;
    iterID @1: UInt64;
}

struct DDKeysDef {
    clientID @0: UInt64;
    chkptID @1: UInt64;
}

struct DDDeregisterClientDef {
    clientID @0: UInt64;
    respFLI @1: Text;
}

struct NoMessageSpecificData {
    none @0: Void;
}

struct ResponseDef {
    ref @0: UInt64;
    err @1: UInt64;
    errInfo @2: Text;
}

struct MessageDef {
    tc  @0: UInt64;
    tag @1: UInt64;
    responseOption: union {
        none @2: Void;
        value @3: ResponseDef;
    }
    union {
        none @4: NoMessageSpecificData;
        shCreateProcessLocalChannel @5: SHCreateProcessLocalChannelDef;
        shCreateProcessLocalChannelResponse @6: SHCreateProcessLocalChannelResponseDef;
        shPushKVL @7: SHSetKVDef;
        shPopKVL @8: SHSetKVDef;
        shGetKVL @9: SHGetKVDef;
        shGetKVLResponse @10: SHGetKVLResponseDef;
        shSetKV @11: SHSetKVDef;
        shGetKV @12: SHGetKVDef;
        shGetKVResponse @13: SHGetKVResponseDef;
        ddRegisterClient @14: DDRegisterClientDef;
        ddRegisterClientResponse @15: DDRegisterClientResponseDef;
        ddDestroy @16: DDDestroyDef;
        ddDestroyManager @17: DDDestroyManagerDef;
        ddRegisterManager @18: DDRegisterManagerDef;
        ddRegisterClientID @19: DDRegisterClientIDDef;
        ddPut @20: DDPutDef;
        ddGet @21: DDGetDef;
        ddPop @22: DDPopDef;
        ddContains @23: DDContainsDef;
        ddGetLength @24: DDGetLengthDef;
        ddGetLengthResponse @25: DDGetLengthResponseDef;
        ddClear @26: DDClearDef;
        ddGetIterator @27: DDGetIteratorDef;
        ddGetIteratorResponse @28: DDGetIteratorResponseDef;
        ddIteratorNext @29: DDIteratorNextDef;
        ddKeys @30: DDKeysDef;
        ddDeregisterClient @31: DDDeregisterClientDef;
        ddCreate @32: DDCreateDef;
        ddRegisterManagerResponse @33: DDRegisterManagerResponseDef;
        ddConnectToManager @34: DDConnectToManagerDef;
        ddConnectToManagerResponse @35: DDConnectToManagerResponseDef;
        ddGetRandomManager @36: DDGetRandomManagerDef;
        ddGetRandomManagerResponse @37: DDGetRandomManagerResponseDef;
        ddManagerStats @38: DDManagerStatsDef;
        ddManagerStatsResponse @39: DDManagerStatsResponseDef;
        ddManagerGetNewestChkptID @40: DDManagerGetNewestChkptID;
        ddManagerGetNewestChkptIDResponse @41: DDManagerGetNewestChkptIDResponse;
    }
}
