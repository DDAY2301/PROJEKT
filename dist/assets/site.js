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
    const lines = [
      "Pozdravljeni,",
      "",
      "pošiljam povpraševanje za projektno spletno stran.",
      "",
      `Organizacija: ${data.get("organization")}`,
      `Kontaktna oseba: ${data.get("name")}`,
      `E-pošta: ${data.get("email")}`,
      `Program: ${data.get("programme")}`,
      `Želeni paket: ${data.get("package")}`,
      `Predviden rok: ${data.get("deadline") || "ni določen"}`,
      `Obstoječa povezava: ${data.get("url") || "ni je"}`,
      "",
      "Opis projekta:",
      `${data.get("description")}`,
      "",
      "Lep pozdrav"
    ];

    const subject = encodeURIComponent(`Povpraševanje – ${data.get("organization")}`);
    const body = encodeURIComponent(lines.join("\n"));
    window.location.href = `mailto:kontakt@projectvisibility.eu?subject=${subject}&body=${body}`;

    if (status) {
      status.classList.add("visible");
      status.textContent = "Odprl se bo vaš e-poštni program s pripravljenim povpraševanjem. Pred pošiljanjem ga lahko še uredite.";
    }
  });
}
