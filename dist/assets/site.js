const briefForm = document.querySelector("[data-brief-form]");

if (briefForm) {
  const status = document.querySelector("[data-form-status]");
  const packageField = briefForm.querySelector("[name='package']");
  const requestedPackage = new URLSearchParams(window.location.search).get("paket");

  if (packageField && ["Start", "Standard", "Premium"].includes(requestedPackage)) {
    packageField.value = requestedPackage;
  }

  briefForm.addEventListener("submit", (event) => {
    event.preventDefault();
    const data = new FormData(briefForm);
    const prefill = {
      organization: data.get("organization") || "",
      contact_name: data.get("name") || "",
      contact_email: data.get("email") || "",
      programme: data.get("programme") || "",
      package: data.get("package") || "Start",
      deadline: data.get("deadline") || "",
      existing_url: data.get("url") || "",
      goal: data.get("description") || ""
    };
    localStorage.setItem("pv_prefill", JSON.stringify(prefill));

    if (status) {
      status.classList.add("visible");
      status.textContent = "Brief je pripravljen. Odpiram builder za popolno prilagoditev in generiranje strani …";
    }

    const pkg = encodeURIComponent(prefill.package);
    window.location.href = `../builder/?paket=${pkg}`;
  });
}
