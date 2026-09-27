package com.adamwyatt.subtitlefinder;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.ActivityNotFoundException;
import android.content.ContentResolver;
import android.content.ContentValues;
import android.content.Intent;
import android.content.SharedPreferences;
import android.database.Cursor;
import android.graphics.Color;
import android.graphics.Typeface;
import android.net.Uri;
import android.os.Bundle;
import android.os.Environment;
import android.provider.MediaStore;
import android.provider.OpenableColumns;
import android.text.InputType;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.widget.ArrayAdapter;
import android.widget.Button;
import android.widget.CheckBox;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ListView;
import android.widget.ProgressBar;
import android.widget.Spinner;
import android.widget.TextView;
import android.widget.Toast;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Locale;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.zip.ZipEntry;
import java.util.zip.ZipInputStream;

public class MainActivity extends Activity {
    private static final int PICK_VIDEO = 2001;
    private static final String PREFS = "subtitle_finder";
    private static final String KEY_API = "subdl_api_key";

    private final ExecutorService executor = Executors.newSingleThreadExecutor();
    private final ArrayList<DisplayItem> items = new ArrayList<>();

    private EditText apiKeyInput;
    private EditText queryInput;
    private EditText yearInput;
    private Spinner searchMode;
    private Spinner mediaType;
    private CheckBox hearingImpairedOnly;
    private TextView status;
    private ProgressBar progress;
    private ListView results;
    private ResultAdapter adapter;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        buildUi();
        loadApiKey();
    }

    private void buildUi() {
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setPadding(dp(34), dp(22), dp(34), dp(22));
        root.setBackgroundColor(Color.rgb(17, 17, 17));

        TextView title = text("Subtitle Finder", 30, true);
        root.addView(title);

        TextView subtitle = text("Fire TV • SubDL v2 • English subtitles • saves to Downloads/Subtitles", 14, false);
        subtitle.setTextColor(Color.LTGRAY);
        LinearLayout.LayoutParams subLp = new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        subLp.setMargins(0, dp(2), 0, dp(14));
        root.addView(subtitle, subLp);

        LinearLayout keyRow = row();
        apiKeyInput = input("SubDL API key");
        apiKeyInput.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_PASSWORD);
        keyRow.addView(apiKeyInput, weight(1));

        Button saveKey = button("Save");
        saveKey.setOnClickListener(v -> saveApiKey());
        keyRow.addView(saveKey);

        Button testKey = button("Test key");
        LinearLayout.LayoutParams testLp = new LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        testLp.setMargins(dp(8), 0, 0, 0);
        keyRow.addView(testKey, testLp);
        testKey.setOnClickListener(v -> testApiKey());
        root.addView(keyRow);

        TextView keyHelp = text("Uses the current SubDL v2 API. Your key stays on this Fire TV.", 12, false);
        keyHelp.setTextColor(Color.GRAY);
        LinearLayout.LayoutParams helpLp = new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        helpLp.setMargins(0, 0, 0, dp(12));
        root.addView(keyHelp, helpLp);

        LinearLayout options = row();
        searchMode = spinner(new String[]{"Title search", "Filename match"});
        mediaType = spinner(new String[]{"Movie", "TV"});
        options.addView(searchMode, weight(1));
        LinearLayout.LayoutParams mediaLp = weight(1);
        mediaLp.setMargins(dp(10), 0, 0, 0);
        options.addView(mediaType, mediaLp);
        root.addView(options);

        LinearLayout searchRow = row();
        queryInput = input("Movie/show title or release filename");
        searchRow.addView(queryInput, weight(1));

        yearInput = input("Year");
        yearInput.setInputType(InputType.TYPE_CLASS_NUMBER);
        LinearLayout.LayoutParams yearLp = new LinearLayout.LayoutParams(dp(120), ViewGroup.LayoutParams.WRAP_CONTENT);
        yearLp.setMargins(dp(10), 0, 0, 0);
        searchRow.addView(yearInput, yearLp);
        root.addView(searchRow);

        LinearLayout buttons = row();
        Button pickFile = button("Select video file");
        pickFile.setOnClickListener(v -> pickVideoFile());
        buttons.addView(pickFile, weight(1));

        Button search = button("Search");
        search.setOnClickListener(v -> doSearch());
        LinearLayout.LayoutParams searchLp = weight(1);
        searchLp.setMargins(dp(10), 0, 0, 0);
        buttons.addView(search, searchLp);
        root.addView(buttons);

        hearingImpairedOnly = new CheckBox(this);
        hearingImpairedOnly.setText("Hearing-impaired subtitles only");
        hearingImpairedOnly.setTextColor(Color.WHITE);
        hearingImpairedOnly.setTextSize(14);
        hearingImpairedOnly.setFocusable(true);
        LinearLayout.LayoutParams hiLp = new LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        hiLp.setMargins(0, dp(2), 0, dp(4));
        root.addView(hearingImpairedOnly, hiLp);

        LinearLayout statusRow = row();
        progress = new ProgressBar(this);
        progress.setVisibility(View.GONE);
        statusRow.addView(progress, new LinearLayout.LayoutParams(dp(32), dp(32)));

        status = text("Title search now shows matching movies first. Select the correct movie, then choose its subtitle.", 14, false);
        status.setTextColor(Color.LTGRAY);
        LinearLayout.LayoutParams stLp = weight(1);
        stLp.gravity = Gravity.CENTER_VERTICAL;
        stLp.setMargins(dp(10), 0, 0, 0);
        statusRow.addView(status, stLp);
        root.addView(statusRow);

        results = new ListView(this);
        results.setDividerHeight(dp(1));
        results.setFocusable(true);
        adapter = new ResultAdapter();
        results.setAdapter(adapter);
        results.setOnItemClickListener((parent, view, position, id) -> {
            DisplayItem item = items.get(position);
            if (item.title != null) {
                fetchSubtitlesForTitle(item.title);
            } else if (item.subtitle != null) {
                confirmDownload(item.subtitle);
            }
        });

        LinearLayout.LayoutParams listLp = new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f);
        root.addView(results, listLp);
        setContentView(root);
    }

    private void loadApiKey() {
        apiKeyInput.setText(getSharedPreferences(PREFS, MODE_PRIVATE).getString(KEY_API, ""));
    }

    private void saveApiKey() {
        String key = apiKeyInput.getText().toString().trim();
        getSharedPreferences(PREFS, MODE_PRIVATE).edit().putString(KEY_API, key).apply();
        Toast.makeText(this, key.isEmpty() ? "API key cleared" : "API key saved", Toast.LENGTH_SHORT).show();
    }

    private void testApiKey() {
        final String key = apiKeyInput.getText().toString().trim();
        if (key.isEmpty()) {
            status.setText("Enter your SubDL API key first.");
            apiKeyInput.requestFocus();
            return;
        }

        saveApiKey();
        setBusy(true, "Testing API key…");
        executor.execute(() -> {
            try {
                JSONObject root = getJson("https://api.subdl.com/api/v2/me", key);
                String plan = firstNonBlank(root.optString("plan", ""), root.optString("tier", ""));
                runOnUiThread(() -> setBusy(false, "API key is valid" + (plan.isEmpty() ? "." : " • Plan: " + plan)));
            } catch (Exception ex) {
                runOnUiThread(() -> setBusy(false, "API key test failed: " + readableError(ex)));
            }
        });
    }

    private void pickVideoFile() {
        try {
            Intent i = new Intent(Intent.ACTION_OPEN_DOCUMENT);
            i.addCategory(Intent.CATEGORY_OPENABLE);
            i.setType("video/*");
            startActivityForResult(i, PICK_VIDEO);
        } catch (ActivityNotFoundException ex) {
            Toast.makeText(this, "No Fire TV file picker is available. Choose Filename match and type the exact video filename.", Toast.LENGTH_LONG).show();
        }
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode == PICK_VIDEO && resultCode == RESULT_OK && data != null && data.getData() != null) {
            String name = getDisplayName(data.getData());
            if (name != null && !name.isEmpty()) {
                queryInput.setText(name);
                searchMode.setSelection(1);
                yearInput.setText("");
                status.setText("Selected: " + name + " • Filename matching ranks subtitles by release similarity.");
            }
        }
    }

    private String getDisplayName(Uri uri) {
        Cursor c = null;
        try {
            c = getContentResolver().query(uri, new String[]{OpenableColumns.DISPLAY_NAME}, null, null, null);
            if (c != null && c.moveToFirst()) {
                int idx = c.getColumnIndex(OpenableColumns.DISPLAY_NAME);
                if (idx >= 0) return c.getString(idx);
            }
        } catch (Exception ignored) {
        } finally {
            if (c != null) c.close();
        }
        return uri.getLastPathSegment();
    }

    private void doSearch() {
        final String apiKey = apiKeyInput.getText().toString().trim();
        final String query = queryInput.getText().toString().trim();

        if (apiKey.isEmpty()) {
            status.setText("Add your SubDL API key first.");
            apiKeyInput.requestFocus();
            return;
        }
        if (query.length() < 2) {
            status.setText("Enter at least 2 characters.");
            queryInput.requestFocus();
            return;
        }

        saveApiKey();
        if (searchMode.getSelectedItemPosition() == 1) {
            searchFilenameV2(apiKey, query);
        } else {
            searchTitlesV2(apiKey, query);
        }
    }

    private void searchTitlesV2(final String apiKey, final String query) {
        final String type = mediaType.getSelectedItemPosition() == 0 ? "movie" : "tv";
        final String preferredYear = yearInput.getText().toString().trim();

        setBusy(true, "Searching SubDL titles…");
        clearResults();

        executor.execute(() -> {
            try {
                String url = "https://api.subdl.com/api/v2/movies/search?q=" + enc(query)
                        + "&type=" + type + "&limit=20";
                JSONObject root = getJson(url, apiKey);
                JSONArray arr = root.optJSONArray("results");
                ArrayList<DisplayItem> found = new ArrayList<>();

                if (arr != null) {
                    if (!preferredYear.isEmpty()) {
                        for (int i = 0; i < arr.length(); i++) {
                            JSONObject o = arr.optJSONObject(i);
                            if (o != null && preferredYear.equals(String.valueOf(o.optInt("year", 0)))) {
                                addTitle(found, o);
                            }
                        }
                    }
                    for (int i = 0; i < arr.length(); i++) {
                        JSONObject o = arr.optJSONObject(i);
                        if (o == null) continue;
                        if (!preferredYear.isEmpty() && preferredYear.equals(String.valueOf(o.optInt("year", 0)))) continue;
                        addTitle(found, o);
                    }
                }

                runOnUiThread(() -> {
                    items.clear();
                    items.addAll(found);
                    adapter.notifyDataSetChanged();
                    setBusy(false, found.isEmpty()
                            ? "No matching titles returned by SubDL."
                            : "Select the correct title below. The year is shown so cataloguing differences such as 2023/2025 are easy to spot.");
                    if (!found.isEmpty()) results.requestFocus();
                });
            } catch (Exception ex) {
                runOnUiThread(() -> setBusy(false, "Title search failed: " + readableError(ex)));
            }
        });
    }

    private void addTitle(ArrayList<DisplayItem> found, JSONObject o) {
        Object idValue = o.opt("sd_id");
        String sdId = idValue == null || idValue == JSONObject.NULL ? "" : String.valueOf(idValue);
        if (sdId.isEmpty()) return;

        String name = firstNonBlank(o.optString("name", ""), o.optString("original_name", ""), "Unknown title");
        int year = o.optInt("year", 0);
        int count = o.optInt("subtitles_count", -1);
        String type = firstNonBlank(o.optString("type", ""), "movie");
        String imdb = o.optString("imdb_id", "");
        found.add(DisplayItem.forTitle(new TitleItem(sdId, name, year, count, type, imdb)));
    }

    private void fetchSubtitlesForTitle(final TitleItem title) {
        final String apiKey = apiKeyInput.getText().toString().trim();
        setBusy(true, "Loading English subtitles for " + title.name + "…");
        clearResults();

        executor.execute(() -> {
            try {
                StringBuilder u = new StringBuilder("https://api.subdl.com/api/v2/subtitles/search?sd_id=");
                u.append(enc(title.sdId));
                u.append("&languages=en&unpack=1");
                JSONObject root = getJson(u.toString(), apiKey);
                ArrayList<SubtitleItem> found = parseSubtitles(root, hearingImpairedOnly.isChecked());

                runOnUiThread(() -> {
                    items.clear();
                    for (SubtitleItem s : found) items.add(DisplayItem.forSubtitle(s));
                    adapter.notifyDataSetChanged();
                    setBusy(false, found.isEmpty()
                            ? "SubDL found " + title.name + (title.year > 0 ? " (" + title.year + ")" : "") + " but returned no English subtitle files."
                            : found.size() + " English subtitle option" + (found.size() == 1 ? "" : "s") + " for " + title.name + ". Select one to download.");
                    if (!found.isEmpty()) results.requestFocus();
                });
            } catch (Exception ex) {
                runOnUiThread(() -> setBusy(false, "Subtitle search failed: " + readableError(ex)));
            }
        });
    }

    private void searchFilenameV2(final String apiKey, final String filename) {
        final String type = mediaType.getSelectedItemPosition() == 0 ? "movie" : "tv";
        final boolean hiOnly = hearingImpairedOnly.isChecked();

        setBusy(true, "Matching release filename…");
        clearResults();

        executor.execute(() -> {
            try {
                StringBuilder u = new StringBuilder("https://api.subdl.com/api/v2/files/search?filename=");
                u.append(enc(filename));
                u.append("&languages=en&type=").append(type);
                u.append("&subs_per_page=30");
                if (hiOnly) u.append("&hi=1");

                JSONObject root = getJson(u.toString(), apiKey);
                ArrayList<SubtitleItem> found = parseSubtitles(root, hiOnly);
                JSONObject match = root.optJSONObject("match");
                String matchedTitle = "";
                if (match != null) {
                    matchedTitle = firstNonBlank(match.optString("title", ""), "");
                    int matchYear = match.optInt("year", 0);
                    if (!matchedTitle.isEmpty() && matchYear > 0) matchedTitle += " (" + matchYear + ")";
                }

                final String finalMatchedTitle = matchedTitle;
                runOnUiThread(() -> {
                    items.clear();
                    for (SubtitleItem s : found) items.add(DisplayItem.forSubtitle(s));
                    adapter.notifyDataSetChanged();
                    if (found.isEmpty()) {
                        setBusy(false, finalMatchedTitle.isEmpty()
                                ? "SubDL could not match that filename. Try Title search."
                                : "Matched " + finalMatchedTitle + " but found no English subtitle files.");
                    } else {
                        setBusy(false, (finalMatchedTitle.isEmpty() ? "" : "Matched " + finalMatchedTitle + " • ")
                                + found.size() + " result" + (found.size() == 1 ? "" : "s") + ", ranked by release match.");
                        results.requestFocus();
                    }
                });
            } catch (Exception ex) {
                runOnUiThread(() -> setBusy(false, "Filename search failed: " + readableError(ex)));
            }
        });
    }

    private ArrayList<SubtitleItem> parseSubtitles(JSONObject root, boolean hiOnly) {
        ArrayList<SubtitleItem> found = new ArrayList<>();
        JSONArray subs = root.optJSONArray("subtitles");
        if (subs == null) return found;

        for (int i = 0; i < subs.length(); i++) {
            JSONObject s = subs.optJSONObject(i);
            if (s == null) continue;

            boolean parentHi = optBooleanLoose(s, "hi", false);
            JSONArray unpack = s.optJSONArray("unpack_files");

            if (unpack != null && unpack.length() > 0) {
                for (int j = 0; j < unpack.length(); j++) {
                    JSONObject f = unpack.optJSONObject(j);
                    if (f == null) continue;
                    boolean fileHi = f.has("hi") ? optBooleanLoose(f, "hi", parentHi) : parentHi;
                    if (hiOnly && !fileHi) continue;

                    String url = firstNonBlank(f.optString("url", ""), "");
                    String nId = firstNonBlank(s.optString("n_id", ""), f.optString("n_id", ""));
                    if (url.isEmpty() && nId.isEmpty()) continue;

                    found.add(new SubtitleItem(
                            releaseName(f, s),
                            firstNonBlank(f.optString("name", ""), s.optString("name", "")),
                            url,
                            nId,
                            languageName(f, s),
                            fileHi,
                            firstNonBlank(f.optString("fps", ""), s.optString("fps", "")),
                            firstNonBlank(f.optString("format", ""), extension(f.optString("name", ""))),
                            optDoubleLoose(s, "match_score", -1)
                    ));
                }
            } else {
                boolean hi = optBooleanLoose(s, "hi", false);
                if (hiOnly && !hi) continue;

                String url = firstNonBlank(s.optString("url", ""), s.optString("download_url", ""));
                String nId = firstNonBlank(s.optString("n_id", ""), s.optString("nid", ""));
                if (url.isEmpty() && nId.isEmpty()) continue;

                found.add(new SubtitleItem(
                        releaseName(s, null),
                        s.optString("name", ""),
                        url,
                        nId,
                        firstNonBlank(s.optString("language", ""), s.optString("lang", ""), "English"),
                        hi,
                        firstNonBlank(s.optString("fps", ""), ""),
                        firstNonBlank(s.optString("format", ""), extension(s.optString("name", ""))),
                        optDoubleLoose(s, "match_score", -1)
                ));
            }
        }
        return found;
    }

    private String releaseName(JSONObject primary, JSONObject fallback) {
        String release = firstNonBlank(
                primary == null ? "" : primary.optString("release_name", ""),
                fallback == null ? "" : fallback.optString("release_name", ""),
                primary == null ? "" : primary.optString("name", ""),
                fallback == null ? "" : fallback.optString("name", "")
        );

        if (release.isEmpty() && primary != null) {
            JSONArray releases = primary.optJSONArray("releases");
            if (releases != null && releases.length() > 0) release = releases.optString(0, "");
        }
        return release.isEmpty() ? "English subtitle" : release;
    }

    private String languageName(JSONObject primary, JSONObject fallback) {
        return firstNonBlank(
                primary == null ? "" : primary.optString("language", ""),
                primary == null ? "" : primary.optString("lang", ""),
                fallback == null ? "" : fallback.optString("language", ""),
                fallback == null ? "" : fallback.optString("lang", ""),
                "English"
        );
    }

    private JSONObject getJson(String url, String apiKey) throws Exception {
        HttpURLConnection conn = null;
        try {
            conn = (HttpURLConnection) new URL(url).openConnection();
            conn.setConnectTimeout(12000);
            conn.setReadTimeout(22000);
            conn.setRequestProperty("Accept", "application/json");
            conn.setRequestProperty("Authorization", "Bearer " + apiKey);
            conn.setRequestProperty("X-API-Key", apiKey);
            conn.setRequestProperty("User-Agent", "SubtitleFinderFireTV/1.1");

            int code = conn.getResponseCode();
            InputStream in = code >= 200 && code < 300 ? conn.getInputStream() : conn.getErrorStream();
            String body = readText(in);

            if (code < 200 || code >= 300) {
                String apiMessage = extractApiError(body);
                throw new IOException("HTTP " + code + (apiMessage.isEmpty() ? "" : " • " + apiMessage));
            }

            if (body.trim().isEmpty()) throw new IOException("SubDL returned an empty response.");
            return new JSONObject(body);
        } finally {
            if (conn != null) conn.disconnect();
        }
    }

    private static String extractApiError(String body) {
        try {
            JSONObject root = new JSONObject(body);
            Object error = root.opt("error");
            if (error instanceof JSONObject) {
                JSONObject e = (JSONObject) error;
                return firstNonBlank(e.optString("message", ""), e.optString("code", ""));
            }
            if (error != null && error != JSONObject.NULL) return String.valueOf(error);
            return root.optString("message", "");
        } catch (Exception ignored) {
            return shortText(body);
        }
    }

    private void confirmDownload(SubtitleItem item) {
        StringBuilder message = new StringBuilder(item.release);
        if (item.matchScore >= 0) message.append("\nMatch score: ").append(Math.round(item.matchScore * 100)).append("%");
        message.append("\n\nSave to Downloads/Subtitles?");
        new AlertDialog.Builder(this)
                .setTitle("Download subtitle?")
                .setMessage(message.toString())
                .setNegativeButton("Cancel", null)
                .setPositiveButton("Download", (d, which) -> download(item))
                .show();
    }

    private void download(final SubtitleItem item) {
        final String apiKey = apiKeyInput.getText().toString().trim();
        setBusy(true, "Downloading subtitle…");

        executor.execute(() -> {
            try {
                DownloadPayload payload = fetchDownload(item, apiKey);
                Extracted extracted = extractSubtitle(payload.bytes, firstNonBlank(item.fileName, payload.suggestedName));
                if (extracted == null) throw new IOException("The download did not contain an SRT/ASS/VTT subtitle.");

                String base = sanitize(firstNonBlank(item.release, "subtitle"));
                if (base.length() > 90) base = base.substring(0, 90);
                String fileName = base + "-EN." + extracted.extension;
                Uri saved = saveToDownloads(fileName, extracted.bytes, extracted.extension);
                if (saved == null) throw new IOException("Could not save the subtitle file.");

                final String finalFileName = fileName;
                runOnUiThread(() -> {
                    setBusy(false, "Saved: Downloads/Subtitles/" + finalFileName + " • In VLC choose Select subtitle file.");
                    Toast.makeText(this, "Subtitle downloaded", Toast.LENGTH_SHORT).show();
                });
            } catch (Exception ex) {
                runOnUiThread(() -> setBusy(false, "Download failed: " + readableError(ex)));
            }
        });
    }

    private DownloadPayload fetchDownload(SubtitleItem item, String apiKey) throws Exception {
        String url;
        boolean apiEndpoint = false;

        if (!item.url.isEmpty()) {
            url = normalizeDownloadUrl(item.url);
        } else if (!item.nId.isEmpty()) {
            url = "https://api.subdl.com/api/v2/subtitles/" + enc(item.nId) + "/download?format=file";
            apiEndpoint = true;
        } else {
            throw new IOException("No download URL was supplied by SubDL.");
        }

        HttpURLConnection conn = null;
        try {
            conn = (HttpURLConnection) new URL(url).openConnection();
            conn.setConnectTimeout(12000);
            conn.setReadTimeout(30000);
            conn.setInstanceFollowRedirects(true);
            conn.setRequestProperty("User-Agent", "SubtitleFinderFireTV/1.1");
            if (url.contains("subdl.com")) {
                conn.setRequestProperty("X-API-Key", apiKey);
                if (apiEndpoint) conn.setRequestProperty("Authorization", "Bearer " + apiKey);
            }

            int code = conn.getResponseCode();
            InputStream in = code >= 200 && code < 300 ? conn.getInputStream() : conn.getErrorStream();
            byte[] data = readBytes(in);
            String contentType = conn.getContentType();

            if (code < 200 || code >= 300) {
                throw new IOException("HTTP " + code + " • " + extractApiError(new String(data, StandardCharsets.UTF_8)));
            }

            if (contentType != null && contentType.toLowerCase(Locale.US).contains("json")) {
                JSONObject root = new JSONObject(new String(data, StandardCharsets.UTF_8));
                String next = firstNonBlank(root.optString("url", ""), root.optString("download_url", ""));
                if (!next.isEmpty() && !next.equals(url)) {
                    SubtitleItem redirected = new SubtitleItem(item.release, item.fileName, next, "", item.language, item.hi, item.fps, item.format, item.matchScore);
                    return fetchDownload(redirected, apiKey);
                }
            }

            return new DownloadPayload(data, fileNameFromUrl(url));
        } finally {
            if (conn != null) conn.disconnect();
        }
    }

    private Uri saveToDownloads(String fileName, byte[] bytes, String ext) throws IOException {
        ContentResolver resolver = getContentResolver();

        if (android.os.Build.VERSION.SDK_INT >= 29) {
            ContentValues values = new ContentValues();
            values.put(MediaStore.Downloads.DISPLAY_NAME, fileName);
            values.put(MediaStore.Downloads.MIME_TYPE, mimeFor(ext));
            values.put(MediaStore.Downloads.RELATIVE_PATH, Environment.DIRECTORY_DOWNLOADS + "/Subtitles");
            values.put(MediaStore.Downloads.IS_PENDING, 1);

            Uri uri = resolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, values);
            if (uri == null) return null;

            try (OutputStream out = resolver.openOutputStream(uri)) {
                if (out == null) throw new IOException("Unable to open output file");
                out.write(bytes);
            }

            ContentValues done = new ContentValues();
            done.put(MediaStore.Downloads.IS_PENDING, 0);
            resolver.update(uri, done, null, null);
            return uri;
        } else {
            java.io.File dir = new java.io.File(Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS), "Subtitles");
            if (!dir.exists() && !dir.mkdirs()) throw new IOException("Could not create Downloads/Subtitles");
            java.io.File outFile = new java.io.File(dir, fileName);
            try (java.io.FileOutputStream out = new java.io.FileOutputStream(outFile)) {
                out.write(bytes);
            }
            return Uri.fromFile(outFile);
        }
    }

    private Extracted extractSubtitle(byte[] data, String suggestedName) throws IOException {
        if (data == null || data.length == 0) return null;

        if (data.length >= 2 && data[0] == 'P' && data[1] == 'K') {
            ZipInputStream zis = new ZipInputStream(new ByteArrayInputStream(data));
            ZipEntry e;
            while ((e = zis.getNextEntry()) != null) {
                if (e.isDirectory()) continue;
                String ext = extension(e.getName());
                if (isSubtitleExt(ext)) {
                    ByteArrayOutputStream out = new ByteArrayOutputStream();
                    byte[] buf = new byte[8192];
                    int n;
                    while ((n = zis.read(buf)) >= 0) out.write(buf, 0, n);
                    return new Extracted(out.toByteArray(), ext);
                }
            }
            return null;
        }

        String ext = extension(suggestedName);
        if (!isSubtitleExt(ext)) ext = "srt";
        return new Extracted(data, ext);
    }

    private static String normalizeDownloadUrl(String value) {
        if (value.startsWith("http://") || value.startsWith("https://")) return value;
        if (!value.startsWith("/")) value = "/" + value;
        return "https://dl.subdl.com" + value;
    }

    private static String fileNameFromUrl(String value) {
        if (value == null) return "";
        int q = value.indexOf('?');
        if (q >= 0) value = value.substring(0, q);
        int slash = value.lastIndexOf('/');
        return slash >= 0 ? value.substring(slash + 1) : value;
    }

    private void clearResults() {
        items.clear();
        if (adapter != null) adapter.notifyDataSetChanged();
    }

    private void setBusy(boolean busy, String message) {
        progress.setVisibility(busy ? View.VISIBLE : View.GONE);
        status.setText(message);
        results.setEnabled(!busy);
    }

    private static String readableError(Exception ex) {
        String m = ex.getMessage();
        if (m == null || m.trim().isEmpty()) m = ex.getClass().getSimpleName();
        if (m.contains("401") || m.toLowerCase(Locale.US).contains("unauthorized")) {
            return m + " • Check the API key with Test key.";
        }
        return m;
    }

    private static boolean optBooleanLoose(JSONObject o, String key, boolean fallback) {
        Object v = o.opt(key);
        if (v instanceof Boolean) return (Boolean) v;
        if (v instanceof Number) return ((Number) v).intValue() != 0;
        if (v instanceof String) {
            String s = ((String) v).trim();
            if ("true".equalsIgnoreCase(s) || "1".equals(s)) return true;
            if ("false".equalsIgnoreCase(s) || "0".equals(s)) return false;
        }
        return fallback;
    }

    private static double optDoubleLoose(JSONObject o, String key, double fallback) {
        Object v = o.opt(key);
        if (v instanceof Number) return ((Number) v).doubleValue();
        if (v instanceof String) {
            try { return Double.parseDouble((String) v); } catch (Exception ignored) {}
        }
        return fallback;
    }

    private static String shortText(String s) {
        if (s == null) return "";
        s = s.replace("\n", " ").replace("\r", " ").trim();
        return s.length() > 180 ? s.substring(0, 180) + "…" : s;
    }

    private static String readText(InputStream in) throws IOException {
        if (in == null) return "";
        return new String(readBytes(in), StandardCharsets.UTF_8);
    }

    private static byte[] readBytes(InputStream in) throws IOException {
        if (in == null) return new byte[0];
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        byte[] buf = new byte[8192];
        int n;
        while ((n = in.read(buf)) >= 0) out.write(buf, 0, n);
        return out.toByteArray();
    }

    private static String enc(String s) throws Exception {
        return URLEncoder.encode(s, "UTF-8");
    }

    private static String firstNonBlank(String... values) {
        for (String v : values) {
            if (v != null && !v.trim().isEmpty() && !"null".equalsIgnoreCase(v.trim())) return v.trim();
        }
        return "";
    }

    private static String extension(String name) {
        if (name == null) return "";
        int q = name.indexOf('?');
        if (q >= 0) name = name.substring(0, q);
        int dot = name.lastIndexOf('.');
        if (dot < 0 || dot == name.length() - 1) return "";
        return name.substring(dot + 1).toLowerCase(Locale.US);
    }

    private static boolean isSubtitleExt(String ext) {
        return "srt".equals(ext) || "ass".equals(ext) || "ssa".equals(ext) || "vtt".equals(ext) || "sub".equals(ext);
    }

    private static String mimeFor(String ext) {
        if ("vtt".equals(ext)) return "text/vtt";
        if ("ass".equals(ext) || "ssa".equals(ext)) return "text/plain";
        return "application/x-subrip";
    }

    private static String sanitize(String s) {
        s = s.replaceAll("[\\\\/:*?\"<>|]", "_").replaceAll("\\s+", " ").trim();
        return s.isEmpty() ? "subtitle" : s;
    }

    private LinearLayout row() {
        LinearLayout l = new LinearLayout(this);
        l.setOrientation(LinearLayout.HORIZONTAL);
        l.setGravity(Gravity.CENTER_VERTICAL);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        lp.setMargins(0, 0, 0, dp(8));
        l.setLayoutParams(lp);
        return l;
    }

    private EditText input(String hint) {
        EditText e = new EditText(this);
        e.setHint(hint);
        e.setSingleLine(true);
        e.setTextColor(Color.WHITE);
        e.setHintTextColor(Color.rgb(155, 155, 155));
        e.setTextSize(16);
        e.setPadding(dp(12), dp(8), dp(12), dp(8));
        e.setFocusable(true);
        return e;
    }

    private Button button(String label) {
        Button b = new Button(this);
        b.setText(label);
        b.setTextSize(14);
        b.setFocusable(true);
        b.setMinHeight(dp(46));
        return b;
    }

    private Spinner spinner(String[] values) {
        Spinner s = new Spinner(this);
        ArrayAdapter<String> a = new ArrayAdapter<String>(this, android.R.layout.simple_spinner_dropdown_item, values);
        s.setAdapter(a);
        s.setFocusable(true);
        s.setMinimumHeight(dp(46));
        return s;
    }

    private TextView text(String value, int size, boolean bold) {
        TextView t = new TextView(this);
        t.setText(value);
        t.setTextColor(Color.WHITE);
        t.setTextSize(size);
        if (bold) t.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        return t;
    }

    private LinearLayout.LayoutParams weight(float weight) {
        return new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, weight);
    }

    private int dp(int value) {
        return Math.round(value * getResources().getDisplayMetrics().density);
    }

    @Override
    protected void onDestroy() {
        executor.shutdownNow();
        super.onDestroy();
    }

    private static final class TitleItem {
        final String sdId;
        final String name;
        final int year;
        final int subtitlesCount;
        final String type;
        final String imdbId;

        TitleItem(String sdId, String name, int year, int subtitlesCount, String type, String imdbId) {
            this.sdId = sdId;
            this.name = name;
            this.year = year;
            this.subtitlesCount = subtitlesCount;
            this.type = type;
            this.imdbId = imdbId;
        }
    }

    private static final class SubtitleItem {
        final String release;
        final String fileName;
        final String url;
        final String nId;
        final String language;
        final boolean hi;
        final String fps;
        final String format;
        final double matchScore;

        SubtitleItem(String release, String fileName, String url, String nId, String language,
                     boolean hi, String fps, String format, double matchScore) {
            this.release = release;
            this.fileName = fileName;
            this.url = url == null ? "" : url;
            this.nId = nId == null ? "" : nId;
            this.language = language;
            this.hi = hi;
            this.fps = fps;
            this.format = format;
            this.matchScore = matchScore;
        }
    }

    private static final class DisplayItem {
        final TitleItem title;
        final SubtitleItem subtitle;

        private DisplayItem(TitleItem title, SubtitleItem subtitle) {
            this.title = title;
            this.subtitle = subtitle;
        }

        static DisplayItem forTitle(TitleItem t) { return new DisplayItem(t, null); }
        static DisplayItem forSubtitle(SubtitleItem s) { return new DisplayItem(null, s); }
    }

    private static final class Extracted {
        final byte[] bytes;
        final String extension;

        Extracted(byte[] bytes, String extension) {
            this.bytes = bytes;
            this.extension = extension;
        }
    }

    private static final class DownloadPayload {
        final byte[] bytes;
        final String suggestedName;

        DownloadPayload(byte[] bytes, String suggestedName) {
            this.bytes = bytes;
            this.suggestedName = suggestedName;
        }
    }

    private final class ResultAdapter extends ArrayAdapter<DisplayItem> {
        ResultAdapter() {
            super(MainActivity.this, android.R.layout.simple_list_item_1, items);
        }

        @Override
        public View getView(int position, View convertView, ViewGroup parent) {
            LinearLayout box;
            TextView primary;
            TextView secondary;

            if (convertView instanceof LinearLayout) {
                box = (LinearLayout) convertView;
                primary = (TextView) box.getChildAt(0);
                secondary = (TextView) box.getChildAt(1);
            } else {
                box = new LinearLayout(MainActivity.this);
                box.setOrientation(LinearLayout.VERTICAL);
                box.setPadding(dp(14), dp(10), dp(14), dp(10));
                box.setFocusable(true);
                box.setClickable(true);
                int[] attrs = new int[]{android.R.attr.selectableItemBackground};
                android.content.res.TypedArray ta = obtainStyledAttributes(attrs);
                box.setBackground(ta.getDrawable(0));
                ta.recycle();

                primary = text("", 17, true);
                secondary = text("", 13, false);
                secondary.setTextColor(Color.LTGRAY);
                box.addView(primary);
                box.addView(secondary);
            }

            DisplayItem row = getItem(position);
            if (row != null && row.title != null) {
                TitleItem t = row.title;
                primary.setText(t.name + (t.year > 0 ? " (" + t.year + ")" : ""));
                StringBuilder meta = new StringBuilder();
                meta.append("Select title");
                if (t.subtitlesCount >= 0) meta.append(" • ").append(t.subtitlesCount).append(" subtitles");
                if (t.imdbId != null && !t.imdbId.isEmpty()) meta.append(" • ").append(t.imdbId);
                secondary.setText(meta.toString());
            } else if (row != null && row.subtitle != null) {
                SubtitleItem s = row.subtitle;
                primary.setText((position + 1) + ". " + s.release);
                StringBuilder meta = new StringBuilder();
                meta.append(firstNonBlank(s.language, "English"));
                if (s.hi) meta.append(" • HI");
                if (s.fps != null && !s.fps.isEmpty()) meta.append(" • ").append(s.fps).append(" fps");
                if (s.format != null && !s.format.isEmpty()) meta.append(" • ").append(s.format.toUpperCase(Locale.US));
                if (s.matchScore >= 0) meta.append(" • match ").append(Math.round(s.matchScore * 100)).append("%");
                meta.append(" • Select to download");
                secondary.setText(meta.toString());
            }

            return box;
        }
    }
}
