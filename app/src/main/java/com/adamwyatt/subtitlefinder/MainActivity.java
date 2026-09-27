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
import android.widget.AdapterView;
import android.widget.ArrayAdapter;
import android.widget.Button;
import android.widget.CheckBox;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ListView;
import android.widget.ProgressBar;
import android.widget.ScrollView;
import android.widget.Spinner;
import android.widget.TextView;
import android.widget.Toast;

import org.json.JSONArray;
import org.json.JSONException;
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
    private final ArrayList<SubtitleItem> items = new ArrayList<>();

    private EditText apiKeyInput;
    private EditText queryInput;
    private EditText yearInput;
    private Spinner searchMode;
    private Spinner mediaType;
    private CheckBox hearingImpairedOnly;
    private TextView status;
    private ProgressBar progress;
    private ListView results;
    private SubtitleAdapter adapter;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        buildUi();
        loadApiKey();
    }

    private void buildUi() {
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setPadding(dp(34), dp(24), dp(34), dp(24));
        root.setBackgroundColor(Color.rgb(17, 17, 17));

        TextView title = text("Subtitle Finder", 30, true);
        root.addView(title);

        TextView subtitle = text("Fire TV subtitle downloader • saves to Downloads/Subtitles", 15, false);
        subtitle.setTextColor(Color.LTGRAY);
        LinearLayout.LayoutParams subLp = new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        subLp.setMargins(0, dp(2), 0, dp(18));
        root.addView(subtitle, subLp);

        LinearLayout keyRow = row();
        apiKeyInput = input("SubDL API key");
        apiKeyInput.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_PASSWORD);
        keyRow.addView(apiKeyInput, weight(1));

        Button saveKey = button("Save key");
        saveKey.setOnClickListener(v -> saveApiKey());
        keyRow.addView(saveKey);
        root.addView(keyRow);

        TextView keyHelp = text("Free key: subdl.com/api  •  Use the Fire TV Remote app keyboard to paste it.", 13, false);
        keyHelp.setTextColor(Color.GRAY);
        LinearLayout.LayoutParams helpLp = new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        helpLp.setMargins(0, dp(4), 0, dp(18));
        root.addView(keyHelp, helpLp);

        LinearLayout options = row();
        searchMode = spinner(new String[]{"Title", "Filename"});
        mediaType = spinner(new String[]{"Movie", "TV"});
        options.addView(searchMode, weight(1));
        options.addView(mediaType, weight(1));
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

        Button search = button("Search English subtitles");
        search.setOnClickListener(v -> doSearch());
        LinearLayout.LayoutParams searchLp = weight(1);
        searchLp.setMargins(dp(10), 0, 0, 0);
        buttons.addView(search, searchLp);
        root.addView(buttons);

        hearingImpairedOnly = new CheckBox(this);
        hearingImpairedOnly.setText("Hearing-impaired subtitles only");
        hearingImpairedOnly.setTextColor(Color.WHITE);
        hearingImpairedOnly.setTextSize(15);
        hearingImpairedOnly.setFocusable(true);
        LinearLayout.LayoutParams hiLp = new LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        hiLp.setMargins(0, dp(8), 0, dp(6));
        root.addView(hearingImpairedOnly, hiLp);

        LinearLayout statusRow = row();
        progress = new ProgressBar(this);
        progress.setVisibility(View.GONE);
        statusRow.addView(progress, new LinearLayout.LayoutParams(dp(34), dp(34)));
        status = text("Enter a title, or select the actual video file for the best match.", 14, false);
        status.setTextColor(Color.LTGRAY);
        LinearLayout.LayoutParams stLp = weight(1);
        stLp.gravity = Gravity.CENTER_VERTICAL;
        stLp.setMargins(dp(10), 0, 0, 0);
        statusRow.addView(status, stLp);
        LinearLayout.LayoutParams statusRowLp = new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        statusRowLp.setMargins(0, dp(8), 0, dp(8));
        root.addView(statusRow, statusRowLp);

        results = new ListView(this);
        results.setDividerHeight(dp(1));
        results.setChoiceMode(ListView.CHOICE_MODE_SINGLE);
        results.setFocusable(true);
        adapter = new SubtitleAdapter();
        results.setAdapter(adapter);
        results.setOnItemClickListener((parent, view, position, id) -> confirmDownload(items.get(position)));
        LinearLayout.LayoutParams listLp = new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f);
        root.addView(results, listLp);

        setContentView(root);
    }

    private void loadApiKey() {
        SharedPreferences p = getSharedPreferences(PREFS, MODE_PRIVATE);
        apiKeyInput.setText(p.getString(KEY_API, ""));
    }

    private void saveApiKey() {
        String key = apiKeyInput.getText().toString().trim();
        getSharedPreferences(PREFS, MODE_PRIVATE).edit().putString(KEY_API, key).apply();
        Toast.makeText(this, key.isEmpty() ? "API key cleared" : "API key saved", Toast.LENGTH_SHORT).show();
    }

    private void pickVideoFile() {
        try {
            Intent i = new Intent(Intent.ACTION_OPEN_DOCUMENT);
            i.addCategory(Intent.CATEGORY_OPENABLE);
            i.setType("video/*");
            startActivityForResult(i, PICK_VIDEO);
        } catch (ActivityNotFoundException ex) {
            Toast.makeText(this, "No file picker is available. Switch to Filename and type the video filename.", Toast.LENGTH_LONG).show();
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
                status.setText("Selected: " + name + ". Filename matching usually gives the best sync.");
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
        final String year = yearInput.getText().toString().trim();

        if (apiKey.isEmpty()) {
            status.setText("Add your free SubDL API key first.");
            apiKeyInput.requestFocus();
            return;
        }
        if (query.isEmpty()) {
            status.setText("Enter a movie/show title or filename.");
            queryInput.requestFocus();
            return;
        }

        saveApiKey();
        setBusy(true, "Searching SubDL…");
        items.clear();
        adapter.notifyDataSetChanged();

        final boolean filenameMode = searchMode.getSelectedItemPosition() == 1;
        final String type = mediaType.getSelectedItemPosition() == 0 ? "movie" : "tv";
        final boolean hiOnly = hearingImpairedOnly.isChecked();

        executor.execute(() -> {
            HttpURLConnection conn = null;
            try {
                StringBuilder u = new StringBuilder("https://api.subdl.com/api/v1/subtitles?");
                u.append("api_key=").append(enc(apiKey));
                if (filenameMode) {
                    u.append("&file_name=").append(enc(query));
                } else {
                    u.append("&film_name=").append(enc(query));
                    u.append("&type=").append(type);
                    if (!year.isEmpty()) u.append("&year=").append(enc(year));
                }
                u.append("&languages=EN&subs_per_page=30&unpack=1&releases=1&hi=1&client=custom_integration");

                conn = (HttpURLConnection) new URL(u.toString()).openConnection();
                conn.setConnectTimeout(12000);
                conn.setReadTimeout(20000);
                conn.setRequestProperty("Accept", "application/json");

                int code = conn.getResponseCode();
                InputStream in = code >= 200 && code < 300 ? conn.getInputStream() : conn.getErrorStream();
                String body = readText(in);

                if (code < 200 || code >= 300) {
                    throw new IOException("SubDL returned HTTP " + code + (body.isEmpty() ? "" : ": " + shortText(body)));
                }

                JSONObject root = new JSONObject(body);
                if (!root.optBoolean("status", false)) {
                    throw new IOException(root.optString("error", "Search failed"));
                }

                JSONArray subs = root.optJSONArray("subtitles");
                ArrayList<SubtitleItem> found = new ArrayList<>();
                if (subs != null) {
                    for (int i = 0; i < subs.length(); i++) {
                        JSONObject s = subs.optJSONObject(i);
                        if (s == null) continue;
                        boolean hi = s.optBoolean("hi", false);
                        if (hiOnly && !hi) continue;

                        JSONArray unpack = s.optJSONArray("unpack_files");
                        if (unpack != null && unpack.length() > 0) {
                            for (int j = 0; j < unpack.length(); j++) {
                                JSONObject f = unpack.optJSONObject(j);
                                if (f == null) continue;
                                boolean fHi = f.has("hi") ? f.optBoolean("hi", false) : hi;
                                if (hiOnly && !fHi) continue;
                                String rawUrl = f.optString("url", "");
                                if (rawUrl.isEmpty()) continue;
                                found.add(new SubtitleItem(
                                        firstNonBlank(f.optString("release_name", ""), s.optString("release_name", ""), f.optString("name", ""), "English subtitle"),
                                        f.optString("name", ""),
                                        normalizeDownloadUrl(rawUrl),
                                        firstNonBlank(f.optString("language", ""), s.optString("language", ""), "EN"),
                                        fHi,
                                        firstNonBlank(s.optString("fps", ""), ""),
                                        f.optString("format", "")
                                ));
                            }
                        } else {
                            String dl = s.optString("url", "");
                            if (dl.isEmpty()) continue;
                            found.add(new SubtitleItem(
                                    firstNonBlank(s.optString("release_name", ""), s.optString("name", ""), "English subtitle"),
                                    s.optString("name", ""),
                                    normalizeDownloadUrl(dl),
                                    firstNonBlank(s.optString("language", ""), "EN"),
                                    hi,
                                    firstNonBlank(s.optString("fps", ""), ""),
                                    ""
                            ));
                        }
                    }
                }

                runOnUiThread(() -> {
                    items.clear();
                    items.addAll(found);
                    adapter.notifyDataSetChanged();
                    setBusy(false, found.isEmpty()
                            ? "No English subtitles found. Try Filename mode with the exact release filename, or remove the year."
                            : found.size() + " subtitle option" + (found.size() == 1 ? "" : "s") + " found. Select one to download.");
                    if (!found.isEmpty()) results.requestFocus();
                });

            } catch (Exception ex) {
                runOnUiThread(() -> setBusy(false, "Search error: " + readableError(ex)));
            } finally {
                if (conn != null) conn.disconnect();
            }
        });
    }

    private void confirmDownload(SubtitleItem item) {
        new AlertDialog.Builder(this)
                .setTitle("Download subtitle?")
                .setMessage(item.release + "\n\nIt will be saved to Downloads/Subtitles.")
                .setNegativeButton("Cancel", null)
                .setPositiveButton("Download", (d, which) -> download(item))
                .show();
    }

    private void download(SubtitleItem item) {
        setBusy(true, "Downloading subtitle…");
        executor.execute(() -> {
            HttpURLConnection conn = null;
            try {
                conn = (HttpURLConnection) new URL(item.url).openConnection();
                conn.setConnectTimeout(12000);
                conn.setReadTimeout(25000);
                conn.setInstanceFollowRedirects(true);
                conn.setRequestProperty("User-Agent", "SubtitleFinderFireTV/1.0");
                int code = conn.getResponseCode();
                if (code < 200 || code >= 300) throw new IOException("Download returned HTTP " + code);
                byte[] data = readBytes(conn.getInputStream());

                Extracted extracted = extractSubtitle(data, item.fileName);
                if (extracted == null) {
                    throw new IOException("The download did not contain an SRT/ASS/VTT subtitle.");
                }

                String base = sanitize(firstNonBlank(item.release, "subtitle"));
                if (base.length() > 90) base = base.substring(0, 90);
                String fileName = base + "-EN." + extracted.extension;
                Uri saved = saveToDownloads(fileName, extracted.bytes, extracted.extension);

                if (saved == null) throw new IOException("Could not save the subtitle file.");

                final String finalFileName = fileName;
                runOnUiThread(() -> {
                    setBusy(false, "Saved: Downloads/Subtitles/" + finalFileName + "  •  In VLC choose Select subtitle file.");
                    Toast.makeText(this, "Subtitle downloaded", Toast.LENGTH_SHORT).show();
                });
            } catch (Exception ex) {
                runOnUiThread(() -> setBusy(false, "Download error: " + readableError(ex)));
            } finally {
                if (conn != null) conn.disconnect();
            }
        });
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

    private void setBusy(boolean busy, String message) {
        progress.setVisibility(busy ? View.VISIBLE : View.GONE);
        status.setText(message);
        results.setEnabled(!busy);
    }

    private static String readableError(Exception ex) {
        String m = ex.getMessage();
        if (m == null || m.trim().isEmpty()) m = ex.getClass().getSimpleName();
        if (m.toLowerCase(Locale.US).contains("api") && m.toLowerCase(Locale.US).contains("key")) {
            return m + " Check the API key saved at the top of the screen.";
        }
        return m;
    }

    private static String shortText(String s) {
        s = s.replace("\n", " ").replace("\r", " ").trim();
        return s.length() > 180 ? s.substring(0, 180) + "…" : s;
    }

    private static String readText(InputStream in) throws IOException {
        if (in == null) return "";
        return new String(readBytes(in), StandardCharsets.UTF_8);
    }

    private static byte[] readBytes(InputStream in) throws IOException {
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
        for (String v : values) if (v != null && !v.trim().isEmpty() && !"null".equalsIgnoreCase(v.trim())) return v.trim();
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
        lp.setMargins(0, 0, 0, dp(10));
        l.setLayoutParams(lp);
        return l;
    }

    private EditText input(String hint) {
        EditText e = new EditText(this);
        e.setHint(hint);
        e.setSingleLine(true);
        e.setTextColor(Color.WHITE);
        e.setHintTextColor(Color.rgb(155, 155, 155));
        e.setTextSize(17);
        e.setPadding(dp(12), dp(9), dp(12), dp(9));
        e.setFocusable(true);
        return e;
    }

    private Button button(String label) {
        Button b = new Button(this);
        b.setText(label);
        b.setTextSize(15);
        b.setFocusable(true);
        b.setMinHeight(dp(48));
        return b;
    }

    private Spinner spinner(String[] values) {
        Spinner s = new Spinner(this);
        ArrayAdapter<String> a = new ArrayAdapter<String>(this, android.R.layout.simple_spinner_dropdown_item, values);
        s.setAdapter(a);
        s.setFocusable(true);
        s.setMinimumHeight(dp(48));
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

    private static final class SubtitleItem {
        final String release;
        final String fileName;
        final String url;
        final String language;
        final boolean hi;
        final String fps;
        final String format;

        SubtitleItem(String release, String fileName, String url, String language, boolean hi, String fps, String format) {
            this.release = release;
            this.fileName = fileName;
            this.url = url;
            this.language = language;
            this.hi = hi;
            this.fps = fps;
            this.format = format;
        }
    }

    private static final class Extracted {
        final byte[] bytes;
        final String extension;
        Extracted(byte[] bytes, String extension) {
            this.bytes = bytes;
            this.extension = extension;
        }
    }

    private final class SubtitleAdapter extends ArrayAdapter<SubtitleItem> {
        SubtitleAdapter() {
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

            SubtitleItem item = getItem(position);
            if (item != null) {
                primary.setText((position + 1) + ". " + item.release);
                StringBuilder meta = new StringBuilder();
                meta.append(item.language == null || item.language.isEmpty() ? "EN" : item.language);
                if (item.hi) meta.append(" • HI");
                if (item.fps != null && !item.fps.isEmpty()) meta.append(" • ").append(item.fps).append(" fps");
                if (item.format != null && !item.format.isEmpty()) meta.append(" • ").append(item.format.toUpperCase(Locale.US));
                meta.append(" • Select to download");
                secondary.setText(meta.toString());
            }
            return box;
        }
    }
}
