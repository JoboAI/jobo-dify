# Privacy policy: Jobo plugin for Dify

Last updated: 2026-11-23

This plugin connects a Dify workspace to the Jobo jobs API. This page says what data it handles.

## What the plugin sends, and where

The plugin sends data to one place only: the Jobo API at `https://connect.jobo.world`. It contacts no other server and includes no analytics, telemetry or tracking.

On each call it sends:

- **Your Jobo API key**, in the `X-Api-Key` request header, to authenticate the request.
- **The query parameters you or your app pass to a tool**: search text, locations, filters, company names or domains, filter-value lookups, and job IDs. Do not put personal data about a person into these fields; they are job-market search terms.
- A `User-Agent` and an `X-Jobo-Client: dify` header that name the plugin and its version.

## What the plugin collects, stores and logs

The plugin itself collects no personal data and keeps no copy of your queries or results. It does not write files, use Dify persistent storage, or log queries, results or the API key. The API key is held by Dify as a secret credential of the plugin, and the plugin only reads it to build the request header. Job listings returned by the API are passed back to your Dify app and are not retained by the plugin.

## What Jobo does with it

The Jobo API is run by Jobo AI LLC. It receives the data listed above and processes it to answer the request and to meter usage and billing on your account (for example, the number of jobs returned). How Jobo handles that data is described in the Jobo privacy policy: <https://jobo.world/privacy>.

## Sensitive data

The plugin is not designed to handle health, financial, biometric, children's or other sensitive personal data, and sends none of it by itself.

## Contact

Questions about this policy: support@jobo.world
