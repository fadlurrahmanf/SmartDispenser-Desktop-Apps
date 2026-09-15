#define AppName "SmartDispenser Perso"
#define AppVersion "1.0.2"
#define AppPublisher "SmartDispenser"
#define AppExeName "SmartDispenserPerso.exe"

[Setup]
AppId={{5E54A12D-384E-482D-A4D2-81556DCB61A1}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\SmartDispenser Perso
DefaultGroupName=SmartDispenser
DisableProgramGroupPage=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=admin
OutputDir=output
OutputBaseFilename=SmartDispenserPersoSetup
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no
UninstallDisplayIcon={app}\{#AppExeName}
SetupLogging=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
Source: "..\release\{#AppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "configure_database.ps1"; DestDir: "{tmp}"; Flags: deleteafterinstall
Source: "install_prerequisites.ps1"; DestDir: "{tmp}"; Flags: deleteafterinstall
Source: "prerequisites\MicrosoftEdgeWebView2RuntimeInstallerX64.exe"; DestDir: "{tmp}"; Flags: deleteafterinstall
Source: "prerequisites\mariadb-11.8.9-winx64.msi"; DestDir: "{tmp}"; Flags: deleteafterinstall
Source: "prerequisites\ch340\*"; DestDir: "{tmp}\ch340"; Flags: recursesubdirs createallsubdirs deleteafterinstall

[Icons]
Name: "{autoprograms}\SmartDispenser\SmartDispenser Perso"; Filename: "{app}\{#AppExeName}"
Name: "{autodesktop}\SmartDispenser Perso"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Buat shortcut di Desktop"; GroupDescription: "Shortcut tambahan:"; Flags: checkedonce

[Run]
Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; Parameters: "-NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File ""{tmp}\install_prerequisites.ps1"" -WebViewInstaller ""{tmp}\MicrosoftEdgeWebView2RuntimeInstallerX64.exe"" -DriverInf ""{tmp}\ch340\CH341SER.INF"" -SuccessMarker ""{tmp}\perso-prerequisites-ready.marker"""; StatusMsg: "Memasang dan memverifikasi WebView2 serta driver CH340..."; Flags: waituntilterminated runhidden; Check: not SkipPrerequisites; AfterInstall: VerifyPrerequisiteInstallation
Filename: "{sys}\msiexec.exe"; Parameters: "/i ""{tmp}\mariadb-11.8.9-winx64.msi"" /qn /norestart PASSWORD=""{code:GetDatabaseAdminPassword}"" SERVICENAME=SmartDispenserMariaDB PORT=3306 ADDLOCAL=DBInstance,Client,MYSQLSERVER,SharedLibraries REMOVE=DEVEL,HeidiSQL"; StatusMsg: "Memasang Database lokal MariaDB..."; Flags: waituntilterminated runhidden dontlogparameters; Check: InstallLocalDatabase
Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; Parameters: "-NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File ""{tmp}\configure_database.ps1"" -AdminPassword ""{code:GetDatabaseAdminPassword}"" -SuccessMarker ""{tmp}\perso-database-ready.marker"""; StatusMsg: "Membuat dan memverifikasi Database aplikasi Perso..."; Flags: waituntilterminated runhidden dontlogparameters; Check: ConfigureDatabase; AfterInstall: VerifyDatabaseProvisioning
Filename: "{app}\{#AppExeName}"; Description: "Jalankan SmartDispenser Perso"; Flags: nowait postinstall skipifsilent

[Code]
var
  DatabasePage: TInputQueryWizardPage;
  DatabaseAlreadyInstalled: Boolean;

function HasDatabaseService: Boolean;
begin
  Result :=
    RegKeyExists(HKLM64, 'SYSTEM\CurrentControlSet\Services\SmartDispenserMariaDB') or
    RegKeyExists(HKLM64, 'SYSTEM\CurrentControlSet\Services\MariaDB') or
    RegKeyExists(HKLM64, 'SYSTEM\CurrentControlSet\Services\mysql') or
    RegKeyExists(HKLM32, 'SYSTEM\CurrentControlSet\Services\SmartDispenserMariaDB') or
    RegKeyExists(HKLM32, 'SYSTEM\CurrentControlSet\Services\MariaDB') or
    RegKeyExists(HKLM32, 'SYSTEM\CurrentControlSet\Services\mysql') or
    FileExists(ExpandConstant('{sd}\xampp\mysql\bin\mysql.exe'));
end;

function CommandLineHas(const Name: String): Boolean;
begin
  Result := Pos('/' + Uppercase(Name), Uppercase(GetCmdTail)) > 0;
end;

function SkipPrerequisites: Boolean;
begin
  Result := CommandLineHas('SKIPPREREQUISITES');
end;

function InstallLocalDatabase: Boolean;
begin
  Result := (not CommandLineHas('SKIPDATABASE')) and (not DatabaseAlreadyInstalled);
end;

function ConfigureDatabase: Boolean;
begin
  Result := not CommandLineHas('SKIPDATABASE');
end;

function GetDatabaseAdminPassword(Param: String): String;
begin
  if DatabasePage.Values[0] = '' then
    Result := '__SMARTDISPENSER_EMPTY_PASSWORD__'
  else
    Result := DatabasePage.Values[0];
end;

procedure InitializeWizard;
begin
  DatabaseAlreadyInstalled := HasDatabaseService;
  DatabasePage := CreateInputQueryPage(
    wpSelectTasks,
    'Konfigurasi Database',
    'Masukkan password administrator Database lokal.',
    'Pada komputer baru, buat password root MariaDB minimal 10 karakter. ' +
    'Jika XAMPP masih memakai root tanpa password, kosongkan kedua kolom. ' +
    'Jika MySQL/MariaDB sudah memakai password, masukkan password root yang berlaku. ' +
    'Password tidak dimasukkan ke source atau EXE aplikasi.');
  DatabasePage.Add('Password administrator:', True);
  DatabasePage.Add('Ulangi password:', True);
end;

procedure VerifyDatabaseProvisioning;
begin
  if not FileExists(ExpandConstant('{tmp}\perso-database-ready.marker')) then
    RaiseException(
      'Konfigurasi Database Perso gagal. Setup dihentikan agar aplikasi tidak dipasang dengan konfigurasi yang rusak. ' +
      'Periksa password root MySQL/MariaDB, pastikan service Database berjalan, lalu jalankan setup kembali.');
end;

procedure VerifyPrerequisiteInstallation;
begin
  if not FileExists(ExpandConstant('{tmp}\perso-prerequisites-ready.marker')) then
    RaiseException(
      'WebView2 atau driver CH340 gagal dipasang. Setup dihentikan agar aplikasi tidak dipasang dalam kondisi belum siap. ' +
      'Jalankan setup kembali sebagai Administrator. Jika tetap gagal, periksa kebijakan instalasi driver Windows.');
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := False;
  if (PageID = DatabasePage.ID) and CommandLineHas('SKIPDATABASE') then
    Result := True;
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if CurPageID = DatabasePage.ID then
  begin
    if DatabasePage.Values[0] <> DatabasePage.Values[1] then
    begin
      MsgBox('Password administrator dan ulangannya tidak sama.', mbError, MB_OK);
      Result := False;
      exit;
    end;
    if (not DatabaseAlreadyInstalled) and (Length(DatabasePage.Values[0]) < 10) then
    begin
      MsgBox('Untuk Database baru, gunakan password administrator minimal 10 karakter.', mbError, MB_OK);
      Result := False;
      exit;
    end;
  end;
end;
