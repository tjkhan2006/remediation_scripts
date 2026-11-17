// Add to the SAME official sample project as TagLinkAudit.cpp.
// HFT macros normally expand to typed function-pointer dereferences. These checks
// intentionally fail compilation if installed headers differ from documented types.
#include "PIHeaders.h"
#include <type_traits>
#include <tuple>

template<class T> struct FunctionSignature;
template<class R, class... A> struct FunctionSignature<R (*)(A...)> {
    using Result = R;
    using Args = std::tuple<A...>;
};
// x64 Windows has one native calling convention. This probe targets x64 only.
static_assert(sizeof(void*) == 8, "Build the x64 sample configuration");
#define CHECK_API(name, result, ...) \
 static_assert(std::is_same<FunctionSignature<decltype(&name)>::Result, result>::value, #name " return differs"); \
 static_assert(std::is_same<FunctionSignature<decltype(&name)>::Args, std::tuple<__VA_ARGS__>>::value, #name " parameters differ")
CHECK_API(PDSMCIDGetParent, ASBool, ASInt32, CosObj, PDSElement*);
CHECK_API(PDSMCGetParent, void, CosObj, PDSMC, PDSElement*);
CHECK_API(PDSElementGetParent, void, PDSElement, PDSElement*, ASBool*);
CHECK_API(PDSTreeRootGetElementFromID, ASBool, PDSTreeRoot, const char*, ASInt32, PDSElement*);
CHECK_API(PDDocGetStructTreeRoot, ASBool, PDDoc, PDSTreeRoot*);
CHECK_API(PDEContainerGetDict, ASBool, PDEContainer, CosObj*, ASBool*);
CHECK_API(PDEContainerGetContent, PDEContent, PDEContainer);
CHECK_API(PDEFormGetCosObj, void, PDEForm, CosObj*);
#undef CHECK_API
