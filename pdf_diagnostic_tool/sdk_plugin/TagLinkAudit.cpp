// Native diagnostic module for Adobe's official BasicUI x64 plug-in sample.
// STATUS: source only; installed SDK header compilation and Acrobat execution pending.
// No document write, insertion, removal, content commit, or save APIs are used.
#include "PIHeaders.h"
#include "TagLinkAudit.h"
#include <windows.h>
#include <commdlg.h>
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <wchar.h>

static CosObj Get(CosObj obj, const char* key) {
    if (CosObjGetType(obj) == CosStream) obj = CosStreamDict(obj);
    return CosDictGet(obj, ASAtomFromString(key));
}
static void String(FILE* out, const char* s) {
    fputc('"', out);
    if (s) for (const unsigned char* p = (const unsigned char*)s; *p; ++p) {
        if (*p == '"' || *p == '\\') fprintf(out, "\\%c", *p);
        else if (*p < 32 || *p >= 127) fprintf(out, "\\u%04x", *p);
        else fputc(*p, out);
    }
    fputc('"', out);
}
static void Ref(FILE* out, CosObj obj) {
    if (CosObjIsIndirect(obj)) fprintf(out, "\"%llu %u R\"",
        (unsigned long long)CosObjGetID(obj), (unsigned)CosObjGetGeneration(obj));
    else fputs("null", out);
}
static void Error(FILE* out, const char* stage, ASErrorCode code, int page) {
    fputs("{\"event\":\"sdk_exception\",\"stage\":", out); String(out, stage);
    fprintf(out, ",\"page\":%d,\"code\":%llu}\n", page, (unsigned long long)code);
}
struct Audit {
    FILE* out;
    PDSTreeRoot root;
    CosObj* reachable;
    size_t count;
    size_t capacity;
    size_t budget;
    ASBool truncated;
};
static ASBool Contains(Audit* a, CosObj obj) {
    for (size_t i = 0; i < a->count; ++i) if (CosObjEqual(a->reachable[i], obj)) return true;
    return false;
}
static void WalkTree(Audit* a, CosObj obj, unsigned depth) {
    if (depth > 256 || a->budget == 0) { a->truncated = true; return; }
    --a->budget;
    if (CosObjGetType(obj) == CosArray) {
        ASInt32 n = CosArrayLength(obj);
        for (ASInt32 i = 0; i < n; ++i) WalkTree(a, CosArrayGet(obj, i), depth+1);
        return;
    }
    if (CosObjGetType(obj) != CosDict || CosObjGetType(Get(obj, "S")) != CosName) return;
    if (Contains(a, obj)) {
        fputs("{\"event\":\"cycle_or_shared_kid\",\"ref\":", a->out); Ref(a->out, obj); fputs("}\n", a->out); return;
    }
    if (a->count == a->capacity) { a->truncated = true; return; }
    a->reachable[a->count++] = obj;
    fputs("{\"event\":\"reachable_tag\",\"ref\":", a->out); Ref(a->out, obj);
    fputs(",\"type\":", a->out); String(a->out, ASAtomGetString(CosNameValue(Get(obj, "S"))));
    fputs("}\n", a->out);
    // PDSElement is a CosObj type in the official API; validate SDK declaration at build.
    PDSElement parent;
    ASBool isRoot = false;
    DURING
        PDSElementGetParent(obj, &parent, &isRoot);
        fputs("{\"event\":\"tag_parent\",\"tag\":", a->out); Ref(a->out, obj);
        fprintf(a->out, ",\"parent_is_tree_root\":%s,\"parent\":", isRoot ? "true" : "false");
        Ref(a->out, parent); fputs("}\n", a->out);
    HANDLER
        Error(a->out, "PDSElementGetParent", ERRORCODE, 0);
    END_HANDLER
    CosObj id = Get(obj, "ID");
    if (CosObjGetType(id) == CosString) {
        ASInt32 size = 0;
        char* bytes = CosStringValue(id, &size);
        PDSElement found;
        ASBool ok = false;
        DURING
            ok = PDSTreeRootGetElementFromID(a->root, bytes, size, &found);
            fputs("{\"event\":\"structure_id_lookup\",\"tag\":", a->out); Ref(a->out, obj);
            fprintf(a->out, ",\"found\":%s,\"matches\":%s}\n", ok ? "true" : "false",
                ok && CosObjEqual(obj, found) ? "true" : "false");
        HANDLER
            Error(a->out, "PDSTreeRootGetElementFromID", ERRORCODE, 0);
        END_HANDLER
    }
    WalkTree(a, Get(obj, "K"), depth+1);
}
static void ParentLookup(Audit* a, int page, CosObj owner, ASInt32 mcid, PDSMC mc) {
    PDSElement parent;
    ASBool ok = false;
    DURING
        ok = PDSMCIDGetParent(mcid, owner, &parent);
        fprintf(a->out, "{\"event\":\"mcid_parent\",\"page\":%d,\"mcid\":%d,\"owner\":", page, (int)mcid);
        Ref(a->out, owner);
        fprintf(a->out, ",\"found\":%s,\"parent\":", ok ? "true" : "false");
        if (ok) Ref(a->out, parent); else fputs("null", a->out);
        fprintf(a->out, ",\"root_reachable\":%s}\n", ok && Contains(a, parent) ? "true" : "false");
    HANDLER
        Error(a->out, "PDSMCIDGetParent", ERRORCODE, page);
    END_HANDLER
    if (mc) {
        DURING
            PDSMCGetParent(owner, mc, &parent);
            fprintf(a->out, "{\"event\":\"container_parent\",\"page\":%d,\"mcid\":%d,\"parent\":", page, (int)mcid);
            Ref(a->out, parent);
            fprintf(a->out, ",\"root_reachable\":%s}\n", Contains(a, parent) ? "true" : "false");
        HANDLER
            Error(a->out, "PDSMCGetParent", ERRORCODE, page);
        END_HANDLER
    }
}
static void WalkContent(Audit* a, PDEContent content, CosObj owner, int page, unsigned depth) {
    if (!content) return;
    if (depth > 64 || a->budget == 0) { a->truncated = true; return; }
    --a->budget;
    fprintf(a->out, "{\"event\":\"content_owner\",\"page\":%d,\"owner\":", page);
    Ref(a->out, owner);
    CosObj sp = Get(owner, "StructParents");
    fputs(",\"struct_parents\":", a->out);
    if (CosObjGetType(sp) == CosInteger) fprintf(a->out, "%d", (int)CosIntegerValue(sp));
    else fputs("null", a->out);
    fputs("}\n", a->out);
    ASInt32 n = PDEContentGetNumElems(content);
    for (ASInt32 i = 0; i < n; ++i) {
        PDEElement el = PDEContentGetElem(content, i);
        ASInt32 type = PDEObjectGetType((PDEObject)el);
        if (type == kPDEContainer || type == kPDEBeginContainer) {
            CosObj props;
            ASBool inlined = false;
            ASBool hasDict;
            ASAtom tag;
            if (type == kPDEContainer) {
                hasDict = PDEContainerGetDict((PDEContainer)el, &props, &inlined);
                tag = PDEContainerGetMCTag((PDEContainer)el);
            } else {
                hasDict = PDEBeginContainerGetDict((PDEBeginContainer)el, &props, &inlined);
                tag = PDEBeginContainerGetMCTag((PDEBeginContainer)el);
            }
            ASInt32 mcid = -1;
            if (hasDict) {
                CosObj id = Get(props, "MCID");
                if (CosObjGetType(id) == CosInteger) mcid = CosIntegerValue(id);
            }
            fprintf(a->out, "{\"event\":\"container\",\"page\":%d,\"index\":%d,\"depth\":%u,\"mcid\":", page, (int)i, depth);
            if (mcid >= 0) fprintf(a->out, "%d", (int)mcid); else fputs("null", a->out);
            fputs(",\"owner\":", a->out); Ref(a->out, owner);
            fputs(",\"tag\":", a->out); String(a->out, ASAtomGetString(tag));
            fprintf(a->out, ",\"has_dictionary\":%s,\"inline\":%s}\n", hasDict ? "true" : "false", inlined ? "true" : "false");
            if (mcid >= 0) ParentLookup(a, page, owner, mcid, type == kPDEContainer ? (PDSMC)el : NULL);
            // A no-MCID container is recorded without issuing a fabricated MCID lookup.
            if (type == kPDEContainer) WalkContent(a, PDEContainerGetContent((PDEContainer)el), owner, page, depth+1);
        } else if (type == kPDEForm) {
            CosObj stream;
            PDEFormGetCosObj((PDEForm)el, &stream);
            WalkContent(a, PDEFormGetContent((PDEForm)el), stream, page, depth+1);
        }
        // Other PDE types are counted by the static parser. No content is committed.
    }
}

void NSSEAuditActiveDocument() {
    AVDoc av = AVAppGetActiveDoc();
    if (!av) { AVAlertNote("Open a disposable test copy first."); return; }
    wchar_t filename[32768] = L"nsse-live-audit.jsonl";
    OPENFILENAMEW dialog = {};
    dialog.lStructSize = sizeof(dialog);
    dialog.hwndOwner = GetActiveWindow();
    dialog.lpstrFile = filename;
    dialog.nMaxFile = 32768;
    dialog.lpstrFilter = L"JSON Lines\0*.jsonl\0\0";
    dialog.lpstrDefExt = L"jsonl";
    dialog.Flags = OFN_PATHMUSTEXIST | OFN_OVERWRITEPROMPT;
    if (!GetSaveFileNameW(&dialog)) return;
    // Fail closed: the native diagnostic only creates a NEW .jsonl log.
    const wchar_t* suffix = wcsrchr(filename, L'.');
    if (!suffix || _wcsicmp(suffix, L".jsonl")) { AVAlertNote("Choose a new .jsonl log file."); return; }
    HANDLE handle = CreateFileW(filename, GENERIC_WRITE, 0, NULL, CREATE_NEW, FILE_ATTRIBUTE_NORMAL, NULL);
    if (handle == INVALID_HANDLE_VALUE) { AVAlertNote("Log must be a new writable file."); return; }
    CloseHandle(handle);
    FILE* out = NULL;
    if (_wfopen_s(&out, filename, L"wb") || !out) { AVAlertNote("Cannot open log."); return; }
    Audit a = {};
    a.out = out;
    a.capacity = 200000;
    a.budget = 1000000;
    a.reachable = (CosObj*)calloc(a.capacity, sizeof(CosObj));
    if (!a.reachable) { fclose(out); AVAlertNote("Insufficient audit memory."); return; }
    SYSTEMTIME now;
    GetSystemTime(&now);
    fprintf(out, "{\"event\":\"session\",\"schema\":\"nsse-live/1\",\"plugin_version\":\"0.1.0\",\"pointer_bits\":%u,\"utc\":\"%04u-%02u-%02uT%02u:%02u:%02uZ\",\"disk_hash\":null,\"note\":\"Live in-memory state; pair with run manifest, SDK header manifest and static source SHA256.\"}\n",
        (unsigned)(sizeof(void*)*8), now.wYear, now.wMonth, now.wDay, now.wHour, now.wMinute, now.wSecond);
    PDDoc doc = AVDocGetPDDoc(av);
    volatile ASBool treeComplete = false;
    DURING
        if (PDDocGetStructTreeRoot(doc, &a.root)) {
            WalkTree(&a, Get(a.root, "K"), 0);
            treeComplete = !a.truncated;
        } else fputs("{\"event\":\"no_structure_root\"}\n", out);
    HANDLER
        Error(out, "tree_inventory", ERRORCODE, 0);
    END_HANDLER
    ASInt32 pages = PDDocGetNumPages(doc);
    for (ASInt32 p = 0; p < pages; ++p) {
        volatile PDPage page = NULL;
        volatile ASBool acquired = false;
        DURING
            page = PDDocAcquirePage(doc, p);
            PDEContent content = PDPageAcquirePDEContent((PDPage)page, 0);
            acquired = true;
            WalkContent(&a, content, PDPageGetCosObj((PDPage)page), (int)p+1, 0);
        HANDLER
            Error(out, "page_inventory", ERRORCODE, (int)p+1);
        END_HANDLER
        // Balanced acquire/release, including error paths; never SetPDEContent.
        if (acquired) {
            DURING
                PDPageReleasePDEContent((PDPage)page, 0);
            HANDLER
                Error(out, "release_content", ERRORCODE, (int)p+1);
            END_HANDLER
        }
        if (page) {
            DURING
                PDPageRelease((PDPage)page);
            HANDLER
                Error(out, "release_page", ERRORCODE, (int)p+1);
            END_HANDLER
        }
        fflush(out);
    }
    fprintf(out, "{\"event\":\"end\",\"reachable_tags\":%llu,\"tree_complete\":%s,\"truncated\":%s}\n",
        (unsigned long long)a.count, treeComplete ? "true" : "false", a.truncated ? "true" : "false");
    free(a.reachable);
    int failed = ferror(out);
    fclose(out);
    AVAlertNote(failed ? "Log write failed. Discard incomplete log." : "Read-only audit finished. Review exceptions and completeness in the JSONL log.");
}
