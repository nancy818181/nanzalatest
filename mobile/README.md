# Nanza Mobile

Flutter companion for the existing Nanza API. It supports sign-in, company/year
selection, pending approvals, the 13-week cash forecast, overdue AR/AP totals,
AI Accountant questions, and expense claims with receipt attachments queued
for OCR. It does not post or edit accounting entries offline.

## Current mobile implementation and validation status

- `mobile/lib/main.dart` implements login, company/year selection, dashboard
  metrics, pending approval/rejection, offline action queuing, receipt camera
  capture, and multilingual AI Accountant calls.
- API calls use `/api/login`, `/api/companies`, `/api/approvals`,
  `/api/approvals/approve`, `/api/approvals/reject`,
  `/api/reports/cash-forecast/13-week`, `/api/aging`, `/api/expenses`,
  `/api/ocr/queue`, and `/api/ai_chat`. The backend has no singular `/api/approve`
  or `/api/dashboard` route; the app uses the existing routes above.
- Screen walkthrough (mock description; no device screenshot is claimed):
  1. Sign-in screen with server URL, username, and password.
  2. Company/year selector after successful authentication.
  3. Dashboard cards for opening cash, overdue receivables/payables, and pending
     approvals, followed by approval cards and weekly cash-flow rows.
  4. Approval menu offers approve or reject with a reason.
  5. Capture opens the device camera, asks for expense details, saves the claim,
     and sends the image to the company's authenticated OCR queue.
- Flutter/Dart must be installed to run `flutter pub get`, `flutter analyze`,
  widget tests, or build an APK. Those checks are not claimed as passed unless
  run on a machine with the Flutter toolchain.

## Build

1. Install Flutter 3.24 or newer and Android Studio (Android SDK 34+).
2. From this folder, generate the Android/iOS platform scaffolding:

   ```sh
   flutter create . --platforms=android,ios
   flutter pub get
   flutter run
   ```

3. Build Android APK: `flutter build apk --release`.
4. For production, configure HTTPS to the Nanza server and restrict the server
   to trusted networks. The app's server URL is entered at sign-in.

The server must expose the same `/api` endpoints used by the desktop client.
Pending approval lists are cached locally. Approval/rejection actions requested
while offline are queued on the device and submitted on the next successful
refresh; the app reports server-side skips (for example, if the document was
already approved). Receipt uploads are retained as expense attachments and queued with status
`pending`. Queue processing requires a configured OCR worker; this server
change does not itself perform OCR.

The app stores the session token and pending-action queue in device preferences.
Protect devices with the platform lock screen and clear app data when a device
is reassigned.
