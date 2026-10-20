//! Native UI Automation oracle; avoids the host's failing managed proxy registration.
use windows::{
    Win32::{
        Foundation::{E_FAIL, HWND},
        System::Com::{
            CLSCTX_INPROC_SERVER, COINIT_MULTITHREADED, CoCreateInstance, CoInitializeEx,
            CoUninitialize,
        },
        UI::Accessibility::*,
    },
    core::{Error, Result},
};

fn inspect(hwnd: HWND, invoke_fit: bool) -> Result<()> {
    unsafe {
        let automation: IUIAutomation =
            CoCreateInstance(&CUIAutomation, None, CLSCTX_INPROC_SERVER)?;
        let root = automation.ElementFromHandle(hwnd)?;
        let walker = automation.ControlViewWalker()?;
        let mut element = walker.GetFirstChildElement(&root).ok();
        let expected = [
            "Open",
            "Previous",
            "Next",
            "Fit",
            "100%",
            "Rotate",
            "Full screen",
            "Help",
        ];
        let mut found = 0usize;
        while let Some(current) = element {
            let id = current
                .CurrentAutomationId()?
                .to_string()
                .parse::<usize>()
                .unwrap_or(0);
            if (100..108).contains(&id) {
                let name = current.CurrentName()?.to_string();
                let kind = current.CurrentControlType()?;
                println!("CONTROL {id} {name} type={}", kind.0);
                if name != expected[id - 100] || kind != UIA_ButtonControlTypeId {
                    return Err(Error::new(
                        E_FAIL,
                        "Control is not a correctly named UIA button",
                    ));
                }
                let invoke: IUIAutomationInvokePattern =
                    current.GetCurrentPatternAs(UIA_InvokePatternId)?;
                if current.CurrentIsEnabled()?.as_bool()
                    && !current.CurrentIsKeyboardFocusable()?.as_bool()
                {
                    return Err(Error::new(
                        E_FAIL,
                        "Enabled button cannot receive keyboard focus",
                    ));
                }
                if id == 103 && invoke_fit {
                    invoke.Invoke()?;
                }
                found |= 1 << (id - 100);
            }
            element = walker.GetNextSiblingElement(&current).ok();
        }
        if found != 255 {
            return Err(Error::new(
                E_FAIL,
                "The eight toolbar buttons were not all exposed",
            ));
        }
        println!("FOTO_UIA_PASS");
        Ok(())
    }
}

fn main() -> Result<()> {
    let mut arguments = std::env::args().skip(1);
    let handle = arguments
        .next()
        .and_then(|s| s.parse::<usize>().ok())
        .ok_or_else(|| Error::new(E_FAIL, "Use: uia_probe WINDOW_HANDLE [--invoke-fit]"))?;
    let invoke_fit = arguments.next().as_deref() == Some("--invoke-fit");
    unsafe {
        CoInitializeEx(None, COINIT_MULTITHREADED).ok()?;
        let result = inspect(HWND(handle as *mut _), invoke_fit);
        CoUninitialize();
        result
    }
}
