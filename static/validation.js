// -----------------------------
// STUDENT REGISTRATION VALIDATION
// -----------------------------
function validateRegistrationForm() {

    const name = document.getElementById("name").value.trim();
    const regNo = document.getElementById("reg_no").value.trim();
    const email = document.getElementById("email").value.trim();
    const department = document.getElementById("department").value.trim();

    if (name === "" || regNo === "" || email === "" || department === "") {
        alert("All fields are required.");
        return false;
    }

    // Register number minimum length
    if (regNo.length < 5) {
        alert("Register number must be at least 5 characters.");
        return false;
    }

    // Email format check
    const emailPattern = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    if (!emailPattern.test(email)) {
        alert("Please enter a valid email address.");
        return false;
    }

    return confirm("Do you want to submit the registration?");
}

// -----------------------------
// EVENT CREATION VALIDATION
// -----------------------------
function validateEventForm() {

    const eventName = document.getElementById("event_name").value.trim();
    const eventDate = document.getElementById("event_date").value;
    const location = document.getElementById("location").value.trim();

    if (eventName === "" || eventDate === "" || location === "") {
        alert("Please fill all required fields.");
        return false;
    }

    // Prevent past dates
    const today = new Date().toISOString().split("T")[0];
    if (eventDate < today) {
        alert("Event date cannot be in the past.");
        return false;
    }

    return true;
}
