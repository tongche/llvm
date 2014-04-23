#ifndef FUNCTIONPASSMANAGERIMPL_H
#define FUNCTIONPASSMANAGERIMPL_H

#include "llvm/PassManagers.h"
#include "llvm/Assembly/PrintModulePass.h"

namespace llvm {

//===----------------------------------------------------------------------===//
// FunctionPassManagerImpl
//
/// FunctionPassManagerImpl manages FPPassManagers
class FunctionPassManagerImpl : public Pass,
                                public PMDataManager,
                                public PMTopLevelManager {
  virtual void anchor();
private:
  bool wasRun;
public:
  static char ID;
  explicit FunctionPassManagerImpl() :
    Pass(PT_PassManager, ID), PMDataManager(),
    PMTopLevelManager(new FPPassManager()), wasRun(false) {}

  /// add - Add a pass to the queue of passes to run.  This passes ownership of
  /// the Pass to the PassManager.  When the PassManager is destroyed, the pass
  /// will be destroyed as well, so there is no need to delete the pass.  This
  /// implies that all passes MUST be allocated with 'new'.
  void add(Pass *P) {
    schedulePass(P);
  }

  /// createPrinterPass - Get a function printer pass.
  Pass *createPrinterPass(raw_ostream &O, const std::string &Banner) const {
    return createPrintFunctionPass(Banner, &O);
  }

  // Prepare for running an on the fly pass, freeing memory if needed
  // from a previous run.
  void releaseMemoryOnTheFly();

  /// run - Execute all of the passes scheduled for execution.  Keep track of
  /// whether any of the passes modifies the module, and if so, return true.
  bool run(Function &F);

  /// doInitialization - Run all of the initializers for the function passes.
  ///
  bool doInitialization(Module &M);

  /// doFinalization - Run all of the finalizers for the function passes.
  ///
  bool doFinalization(Module &M);


  virtual PMDataManager *getAsPMDataManager() { return this; }
  virtual Pass *getAsPass() { return this; }
  virtual PassManagerType getTopLevelPassManagerType() {
    return PMT_FunctionPassManager;
  }

  /// Pass Manager itself does not invalidate any analysis info.
  void getAnalysisUsage(AnalysisUsage &Info) const {
    Info.setPreservesAll();
  }

  FPPassManager *getContainedManager(unsigned N) {
    assert(N < PassManagers.size() && "Pass number out of range!");
    FPPassManager *FP = static_cast<FPPassManager *>(PassManagers[N]);
    return FP;
  }
};

} // namespace llvm

#endif // FUNCTIONPASSMANAGERIMPL_H
