// Start the portable Core to Map application.
// Author: Ding Qing
// Date: 2026-10-15

using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Net;
using System.Reflection;
using System.Security.Cryptography;
using System.Text;
using System.Web.Script.Serialization;

[assembly: AssemblyTitle("Core to Map")]
[assembly: AssemblyDescription("Core to Map portable launcher")]
[assembly: AssemblyCompany("Ding Qing")]
[assembly: AssemblyProduct("Core to Map")]
[assembly: AssemblyVersion("1.0.0.0")]

internal static class Launcher
{
    private static string PathId(string path)
    {
        using (SHA256 sha = SHA256.Create())
        {
            byte[] bytes = Encoding.UTF8.GetBytes(Path.GetFullPath(path).ToLowerInvariant());
            return BitConverter.ToString(sha.ComputeHash(bytes)).Replace("-", "").ToLowerInvariant();
        }
    }

    private static string RunningUrl(string code, string data)
    {
        string instance = PathId(code);
        string library = PathId(data);
        for (int port = 8051; port <= 8070; port++)
        {
            string url = "http://127.0.0.1:" + port + "/";
            try
            {
                HttpWebRequest request = (HttpWebRequest)WebRequest.Create(url + "health");
                request.Proxy = null;
                request.Timeout = 200;
                request.ReadWriteTimeout = 200;
                using (WebResponse response = request.GetResponse())
                using (StreamReader reader = new StreamReader(response.GetResponseStream()))
                {
                    Dictionary<string, object> health = new JavaScriptSerializer()
                        .Deserialize<Dictionary<string, object>>(reader.ReadToEnd());
                    object value;
                    if (health.TryGetValue("app_id", out value) && (string)value == "hylogger-interval-explorer"
                        && health.TryGetValue("instance_id", out value) && (string)value == instance
                        && health.TryGetValue("data_root_id", out value) && (string)value == library)
                        return url;
                }
            }
            catch (WebException) { }
            catch (IOException) { }
            catch (InvalidOperationException) { }
            catch (ArgumentException) { }
            catch (InvalidCastException) { }
        }
        return null;
    }

    private static int Main()
    {
        Console.Title = "Core to Map";
        string root = Path.GetDirectoryName(Assembly.GetExecutingAssembly().Location);
        string code = Path.Combine(root, "code");
        string data = Path.Combine(root, "data");
        string python = Path.Combine(root, "runtime", "python.exe");
        string script = Path.Combine(code, "launch.py");
        try
        {
            if (!File.Exists(python) || !File.Exists(script))
                throw new FileNotFoundException("Extract the complete package first. Keep CoreToMap.exe beside code, data and runtime.");

            Directory.CreateDirectory(Path.Combine(data, "inbox"));
            string running = RunningUrl(code, data);
            if (running != null)
            {
                Console.WriteLine("Opening Core to Map: " + running);
                Process.Start(new ProcessStartInfo(running) { UseShellExecute = true });
                return 0;
            }

            Console.WriteLine("Core to Map");
            Console.WriteLine("Keep this window open while using the application. Press Ctrl+C to stop.");
            Console.WriteLine("Add GSWA Summary Mineral Log CSVs to data\\inbox, then select Refresh library.");
            Console.WriteLine();
            ProcessStartInfo start = new ProcessStartInfo(python, "-B \"" + script + "\"");
            start.WorkingDirectory = root;
            start.UseShellExecute = false;
            start.EnvironmentVariables["HYLOGGER_DATA_ROOT"] = data;
            start.EnvironmentVariables["PYTHONDONTWRITEBYTECODE"] = "1";
            start.EnvironmentVariables["PYTHONNOUSERSITE"] = "1";
            start.EnvironmentVariables.Remove("PYTHONHOME");
            start.EnvironmentVariables.Remove("PYTHONPATH");
            using (Process process = Process.Start(start))
            {
                process.WaitForExit();
                if (process.ExitCode == 0) return 0;
                Console.Error.WriteLine("The application stopped. See the message above.");
            }
        }
        catch (Exception error)
        {
            Console.Error.WriteLine(error.Message);
        }
        if (!Console.IsInputRedirected)
        {
            Console.WriteLine("Press any key to close.");
            Console.ReadKey(true);
        }
        return 1;
    }
}
