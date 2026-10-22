using System;
using System.Diagnostics;
using System.IO;
using System.Reflection;

internal static class Launcher
{
    private static int Main(string[] args)
    {
        string root = Path.GetDirectoryName(Assembly.GetExecutingAssembly().Location);
        string python = Path.Combine(root, "runtime", "python.exe");
        string entry = Path.Combine(root, "launcher.py");
        try
        {
            if (!File.Exists(python) || !File.Exists(entry))
                throw new FileNotFoundException("Please keep AI-Agent.exe together with runtime and launcher.py.");

            ProcessStartInfo start = new ProcessStartInfo(python);
            start.WorkingDirectory = root;
            start.UseShellExecute = false;
            start.Arguments = "-u -B \"" + entry + "\"";
            foreach (string arg in args)
                start.Arguments += " \"" + arg.Replace("\"", "\\\"") + "\"";
            start.EnvironmentVariables.Remove("PYTHONHOME");
            start.EnvironmentVariables.Remove("PYTHONPATH");
            start.EnvironmentVariables["PYTHONUTF8"] = "1";
            start.EnvironmentVariables["PYTHONNOUSERSITE"] = "1";
            using (Process process = Process.Start(start))
            {
                // Ctrl+C 交由同一個主控台內的 Python 正常停止服務。
                Console.CancelKeyPress += delegate(object sender, ConsoleCancelEventArgs e) { e.Cancel = true; };
                process.WaitForExit();
                if (process.ExitCode != 0 && args.Length == 0)
                {
                    Console.WriteLine("\nStartup failed. Press Enter to close.");
                    Console.ReadLine();
                }
                return process.ExitCode;
            }
        }
        catch (Exception error)
        {
            Console.Error.WriteLine(error.Message);
            if (args.Length == 0)
            {
                Console.WriteLine("Press Enter to close.");
                Console.ReadLine();
            }
            return 1;
        }
    }
}
