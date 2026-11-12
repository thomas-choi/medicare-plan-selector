# HUD USPS ZIP→County API: setup (for Thomas)

Part of design v0.3, signed off 2026-11-12.

Official reference (read 2026-11-12): https://www.huduser.gov/portal/dataset/uspszip-api.html
Status key: **V** = stated on the official HUD page. **L** = the link was found on HUD's own login page. **U** = unverified (HUD's pages returned bot challenges to automated fetches, or the detail isn't documented).

## Steps
1. **Create an account.** Open **https://www.huduser.gov/hudapi/public/register** (**L**: the "REGISTER" link on HUD's login page). When it asks which Datasets APIs you want, **select the USPS Crosswalk dataset API** (**V**: "Sign up for an account and select the Datasets API you want to access"). Exact form fields: **U**.
2. **Confirm your email.** Click the link in HUD User's confirmation email (**V**).
3. **Log in** at **https://www.huduser.gov/hudapi/public/login** (**V**: this page was fetched and shows E-mail/Password fields plus Register and password-reset links).
4. **Create a token.** After logging in, click **"Create New Token"** and copy it. Store it like a password. Token lifetime, expiry and how many tokens you can have: **U**. Note what the page says.
5. **Put it in the server `.env`** (never in git):
   ```
   HUD_API_TOKEN=<paste token>
   HUD_API_BASE=https://www.huduser.gov/hudapi/public/usps
   ```
6. **Test it** from the server shell. Use your own ZIP; `85004` (central Phoenix) is shown as an example:
   ```bash
   curl -s -H "Authorization: Bearer $HUD_API_TOKEN" -G \
        -d 'type=2' -d 'query=85004' \
        https://www.huduser.gov/hudapi/public/usps | python3 -m json.tool | head -40
   ```
   - **Auth:** the header is `Authorization: Bearer <token>`. Only GET requests are allowed, and the response is JSON (**V**).
   - **`type=2`** is the **zip-county** crosswalk (**V**: the type list is ordered 1 zip-tract, **2 zip-county**, 3 zip-cbsa …). `query` is the 5-digit ZIP. A 2-letter state code or `All` also works, from 2021 Q1 onward (**V**).
   - **Optional:** `year=YYYY` and `quarter=1..4`. They default to the latest (**V**).
   - **Response:** `data.results[]` with `geoid` (5-digit state+county FIPS), `res_ratio`, `bus_ratio`, `oth_ratio`, `tot_ratio`, `city` and `state` (**V**).
7. **Read the response codes** (**V**):
   - **200:** OK.
   - **401:** bad token.
   - **403:** your account isn't registered for this dataset. Go back to step 1 and add the USPS Crosswalk dataset.
   - **404:** no data for that query.
   - **406:** the request needs `Accept: application/json`.

## How the app uses it
- The app calls the API only on a cache miss in `zip_county_cache`. It stores the ZIP→FIPS mapping and ratios, **never linked to a user**.
- If a ZIP maps to more than one county, the user picks one, listed in `res_ratio` order.
- **Optional bulk preload:** `selector hud preload --state AZ` uses `query=AZ`, which reduces calls at runtime.
- **Rate limits and Terms of Service:** the HUD page links a "Terms of Service of the HUD User API" (exact URL **U**). Read it before the public launch, especially any limits on call volume and attribution. The app caches aggressively and makes no more than 1 request per second (our own limit).
- **Fallback if the token isn't available by M1:** the quarterly ZIP-COUNTY files at https://www.huduser.gov/portal/datasets/usps_crosswalk.html (**U**: whether a login is needed).
