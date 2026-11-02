package app.done.dan.voicebutton;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.ActivityNotFoundException;
import android.content.Intent;
import android.os.Bundle;

/** Samsung's side-button chooser groups activities by package. Give voice its own package. */
public final class VoiceButtonActivity extends Activity {
    @Override public void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        if (savedInstanceState != null) { finish(); return; }
        try {
            startActivity(new Intent(Intent.ACTION_MAIN)
                .setClassName("app.done.dan", "app.done.dan.voice.DanVoiceShortcutActivity")
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
            finish();
        } catch (ActivityNotFoundException | SecurityException error) {
            new AlertDialog.Builder(this).setTitle("ダンと話す")
                .setMessage("Doneアプリを更新してから、もう一度開いてください。")
                .setPositiveButton("閉じる", (dialog, which) -> finish())
                .setOnCancelListener(dialog -> finish()).show();
        }
    }
}
