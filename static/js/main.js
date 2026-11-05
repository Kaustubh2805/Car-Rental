document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll(".toast").forEach((element) => {
    if (window.bootstrap?.Toast) {
      window.bootstrap.Toast.getOrCreateInstance(element).show();
    }
  });

  document.querySelectorAll("form[data-client-validation]").forEach((form) => {
    form.noValidate = false;
    form.addEventListener("submit", (event) => {
      const pickup = form.querySelector('[name="pickup_datetime"]');
      const returnAt = form.querySelector('[name="return_datetime"]');
      if (pickup && returnAt && pickup.value && returnAt.value) {
        const pickupDate = new Date(pickup.value.replace(" ", "T"));
        const returnDate = new Date(returnAt.value.replace(" ", "T"));
        returnAt.setCustomValidity(
          returnDate > pickupDate ? "" : "Return time must be after pickup time."
        );
      }

      const password = form.querySelector('[name="password1"]');
      const passwordConfirmation = form.querySelector('[name="password2"]');
      if (password && passwordConfirmation) {
        passwordConfirmation.setCustomValidity(
          password.value === passwordConfirmation.value
            ? ""
            : "Passwords do not match."
        );
      }

      if (!form.checkValidity()) {
        event.preventDefault();
        form.reportValidity();
      }
    });

    form.querySelectorAll("input, select, textarea").forEach((field) => {
      field.addEventListener("input", () => field.setCustomValidity(""));
      field.addEventListener("change", () => field.setCustomValidity(""));
    });
  });

  if (window.flatpickr) {
    window.flatpickr(".flatpickr-datetime", {
      enableTime: true,
      time_24hr: true,
      dateFormat: "Y-m-d H:i",
      minDate: "today",
      minuteIncrement: 15,
    });
  }

  document.querySelectorAll("[data-confirm-modal]").forEach((form) => {
    let confirmed = false;
    const modalElement = document.getElementById(form.dataset.confirmModal);
    const confirmButton = modalElement?.querySelector("[data-confirm-submit]");
    if (!modalElement || !confirmButton || !window.bootstrap) {
      return;
    }

    const modal = window.bootstrap.Modal.getOrCreateInstance(modalElement);
    form.addEventListener("submit", (event) => {
      if (confirmed) {
        return;
      }
      event.preventDefault();
      modal.show();
    });
    confirmButton.addEventListener("click", () => {
      confirmed = true;
      form.requestSubmit();
      modal.hide();
    });
  });

  const bookingForm = document.querySelector("[data-availability-url]");
  if (!bookingForm) {
    return;
  }

  const pickup = bookingForm.querySelector('[name="pickup_datetime"]');
  const returnAt = bookingForm.querySelector('[name="return_datetime"]');
  const output = bookingForm.querySelector("[data-quote-output]");
  const errorOutput = bookingForm.querySelector("[data-availability-error]");
  const loadingIndicator = bookingForm.querySelector("[data-quote-loading]");
  const quoteRegion = bookingForm.querySelector("[data-quote-region]");
  const submitButton = bookingForm.querySelector('button[type="submit"]');

  const updateQuote = async () => {
    errorOutput.textContent = "";
    if (!pickup.value || !returnAt.value) {
      output.textContent = "Select pickup and return times to check.";
      submitButton.disabled = false;
      loadingIndicator.hidden = true;
      quoteRegion.setAttribute("aria-busy", "false");
      return;
    }

    const url = new URL(bookingForm.dataset.availabilityUrl, window.location.origin);
    url.searchParams.set("vehicle_id", bookingForm.dataset.vehicleId);
    url.searchParams.set("pickup_datetime", pickup.value);
    url.searchParams.set("return_datetime", returnAt.value);
    submitButton.disabled = true;
    output.textContent = "Checking availability…";
    loadingIndicator.hidden = false;
    quoteRegion.setAttribute("aria-busy", "true");

    try {
      const response = await fetch(url, {
        headers: {"Accept": "application/json"},
      });
      const result = await response.json();
      if (!response.ok) {
        throw new Error(result.error || "Enter valid pickup and return dates.");
      }
      if (!result.available) {
        output.textContent = "Not available for these dates.";
        submitButton.disabled = true;
        return;
      }
      const quote = result.quote;
      output.textContent =
        `${quote.rental_days} day(s) · total ₹${quote.total_amount} ` +
        `· deposit ₹${quote.security_deposit}`;
      submitButton.disabled = false;
    } catch (error) {
      output.textContent = "Availability could not be checked.";
      errorOutput.textContent = error.message;
      submitButton.disabled = false;
    } finally {
      loadingIndicator.hidden = true;
      quoteRegion.setAttribute("aria-busy", "false");
    }
  };

  pickup.addEventListener("change", updateQuote);
  returnAt.addEventListener("change", updateQuote);
});
