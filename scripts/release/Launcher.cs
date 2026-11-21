using System;
using System.Diagnostics;
using System.IO;
using System.Text;
using System.Text.RegularExpressions;
using System.Windows.Forms;

[assembly: System.Reflection.AssemblyTitle("EyE Care")]
[assembly: System.Reflection.AssemblyProduct("EyE Care")]
[assembly: System.Reflection.AssemblyCompany("Suisyokuyuu")]
[assembly: System.Reflection.AssemblyFileVersion("1.0.0.0")]

internal static class Launcher {
    private static string Quote(string value) {
        var result = new StringBuilder("\"");
        int slashes = 0;
        foreach (char c in value) {
            if (c == '\\') { slashes++; continue; }
            result.Append('\\', c == '"' ? 2 * slashes + 1 : slashes);
            result.Append(c);
            slashes = 0;
        }
        return result.Append('\\', 2 * slashes).Append('"').ToString();
    }
    [STAThread]
    private static int Main(string[] args) {
        try {
            string root = AppDomain.CurrentDomain.BaseDirectory;
            bool helper = Path.GetFileName(Application.ExecutablePath).IndexOf("Updater", StringComparison.OrdinalIgnoreCase) >= 0;
            if (helper) {
                int i = Array.IndexOf(args, "--target-dir");
                if (i >= 0 && i+1 < args.Length) root = Path.GetFullPath(args[i+1]);
            }
            string version = File.ReadAllText(Path.Combine(root, "current.txt")).Trim();
            if (!Regex.IsMatch(version, @"\A[0-9]+\.[0-9]+\.[0-9]+\z")) throw new IOException("版本指针无效");
            string app = Path.Combine(root, "versions", version);
            string runtime = File.ReadAllText(Path.Combine(app, "runtime-id.txt")).Trim();
            if (!Regex.IsMatch(runtime, @"\A[0-9a-f]{16}\z")) throw new IOException("运行库编号无效");
            string python = Path.Combine(root, "runtime", runtime, "pythonw.exe");
            string script = Path.Combine(app, helper ? "updater_main.py" : "main.py");
            string boot = "import os,sys,runpy; p=sys.argv.pop(1); sys.argv[0]=p; sys.path.insert(0,os.path.dirname(p)); runpy.run_path(p,run_name='__main__')";
            var command = new StringBuilder("-I -B -c ").Append(Quote(boot)).Append(' ').Append(Quote(script));
            for (int i=0; i<args.Length; ++i) command.Append(' ').Append(Quote(args[i]));
            var start = new ProcessStartInfo(python, command.ToString());
            start.UseShellExecute = false;
            start.WorkingDirectory = root;
            using (var child = Process.Start(start)) { child.WaitForExit(); return child.ExitCode; }
        } catch (Exception e) {
            if (String.IsNullOrEmpty(Environment.GetEnvironmentVariable("EYECARE_TRIAL_READY")))
                MessageBox.Show(e.Message, "EyE Care", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return 1;
        }
    }
}
