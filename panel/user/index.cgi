#!/usr/local/cpanel/3rdparty/bin/perl
use strict;
use warnings;

use Cpanel::AdminBin::Call ();

my $session = $ENV{'REMOTE_USER'} || '';
my $uid_name = getpwuid($>) || '';
if ( $> == 0 || $uid_name ne $session || $session !~ /\A[a-z0-9_]{1,32}\z/ || !-f "/var/cpanel/users/$session" ) {
    print "Status: 403 Forbidden\r\nContent-Type: text/plain; charset=utf-8\r\n\r\nYetkisiz\n";
    exit 0;
}

my $root = '/usr/local/cpanel/base/3rdparty/cpbackup';
my %query = map {
    my ( $key, $value ) = split( /=/, $_, 2 );
    $value = '' if !defined $value;
    $value =~ s/%([0-9A-Fa-f]{2})/chr(hex($1))/eg;
    ( $key, $value );
} split( /&/, $ENV{'QUERY_STRING'} || '' );

if ( my $asset = $query{'asset'} ) {
    serve_asset($asset);
    exit 0;
}

my $action = $query{'action'} || '';
if ( !$action ) {
    serve_page();
    exit 0;
}

if ( ( $ENV{'HTTP_X_CPBACKUP'} || '' ) ne '1' ) {
    send_json(403, '{"ok":false,"error":"Yetkisiz"}');
    exit 0;
}
if ( ( $action eq 'restore' || $action eq 'backup' || $action eq 'partial' || $action eq 'delete' ) && ( $ENV{'REQUEST_METHOD'} || '' ) ne 'POST' ) {
    send_json(405, '{"ok":false,"error":"Bu işlem POST ile yapılmalıdır."}');
    exit 0;
}

my $body = {};
if ( ( $ENV{'CONTENT_LENGTH'} || 0 ) > 0 ) {
    my $length = int( $ENV{'CONTENT_LENGTH'} );
    if ( $length > 200000 ) {
        send_json(400, '{"ok":false,"error":"İstek çok büyük."}');
        exit 0;
    }
    read( STDIN, my $raw, $length );
    if ( $raw =~ /"id"\s*:\s*(\d+)/ ) {
        $body->{'id'} = $1;
    }
    if ( $raw =~ /"confirm"\s*:\s*"([a-z0-9_]{1,32})"/ ) {
        $body->{'confirm'} = $1;
    }
    if ( $action eq 'backup' || $action eq 'partial' ) {
        my $home = ( getpwuid($>) )[7] || '';
        if ( $home =~ m{\A/} && $home !~ m{\.\.} ) {
            if ( open my $request, '>', "$home/.cpbackup-request" ) {
                print {$request} $raw;
                close $request;
            }
        }
    }
}

my $result;
eval {
    if ( $action eq 'list' ) {
        $result = Cpanel::AdminBin::Call::call( 'Cpanel', 'cpbackup', 'LIST' );
    }
    elsif ( $action eq 'log' ) {
        $result = Cpanel::AdminBin::Call::call( 'Cpanel', 'cpbackup', 'LOG', $body->{'id'} || $query{'id'} );
    }
    elsif ( $action eq 'restore' ) {
        $result = Cpanel::AdminBin::Call::call( 'Cpanel', 'cpbackup', 'RESTORE', $body->{'id'}, $body->{'confirm'} );
    }
    elsif ( $action eq 'backup' ) {
        $result = Cpanel::AdminBin::Call::call( 'Cpanel', 'cpbackup', 'BACKUP' );
    }
    elsif ( $action eq 'entries' ) {
        $result = Cpanel::AdminBin::Call::call( 'Cpanel', 'cpbackup', 'ENTRIES', $query{'id'} );
    }
    elsif ( $action eq 'partial' ) {
        $result = Cpanel::AdminBin::Call::call( 'Cpanel', 'cpbackup', 'PARTIAL' );
    }
    elsif ( $action eq 'delete' ) {
        $result = Cpanel::AdminBin::Call::call( 'Cpanel', 'cpbackup', 'DELETE', $body->{'id'} );
    }
    else {
        die "bilinmeyen işlem";
    }
};
if ($@) {
    my $message = $@;
    $message =~ s/\s+\z//;
    $message =~ s/.*at \/.*//s;
    $message =~ s{[\\/]\S+}{}g;
    $message = 'İşlem tamamlanamadı.' if $message !~ /\S/ || length($message) > 300;
    $message =~ s/(["\\])/\\$1/g;
    send_json(400, qq|{"ok":false,"error":"$message"}|);
    exit 0;
}

send_json(200, $result);
exit 0;

sub serve_page {
    my $path = "$root/user.html";
    if ( !-f $path ) {
        print "Status: 503 Error\r\nContent-Type: text/plain; charset=utf-8\r\n\r\nSayfa hazır değil\n";
        return;
    }
    open( my $handle, '<', $path ) or die $!;
    local $/;
    my $html = <$handle>;
    close($handle);
    $html =~ s{\./assets/}{assets/}g;
    my $length = length( $html );
    print "Status: 200 OK\r\nContent-Type: text/html; charset=utf-8\r\n";
    print "X-Content-Type-Options: nosniff\r\nX-Frame-Options: SAMEORIGIN\r\n";
    print "Content-Security-Policy: default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'self'\r\n";
    print "Cache-Control: no-store\r\nContent-Length: $length\r\n\r\n$html";
}

sub serve_asset {
    my ($name) = @_;
    if ( $name !~ /\A[A-Za-z0-9._-]+\z/ || $name =~ /\.\./ ) {
        print "Status: 404 Not Found\r\nContent-Type: text/plain\r\n\r\n";
        return;
    }
    my $path = "$root/assets/$name";
    if ( !-f $path ) {
        print "Status: 404 Not Found\r\nContent-Type: text/plain\r\n\r\n";
        return;
    }
    my $mime = 'application/octet-stream';
    $mime = 'application/javascript; charset=utf-8' if $name =~ /\.js\z/;
    $mime = 'text/css; charset=utf-8'               if $name =~ /\.css\z/;
    open( my $handle, '<', $path ) or die $!;
    local $/;
    my $data = <$handle>;
    close($handle);
    my $length = length($data);
    print "Status: 200 OK\r\nContent-Type: $mime\r\nContent-Length: $length\r\nCache-Control: public, max-age=86400\r\n\r\n$data";
}

sub send_json {
    my ( $code, $body ) = @_;
    my $reason = $code == 200 ? 'OK' : 'Error';
    my $length = length($body);
    print "Status: $code $reason\r\nContent-Type: application/json; charset=utf-8\r\n";
    print "X-Content-Type-Options: nosniff\r\nCache-Control: no-store\r\nContent-Length: $length\r\n\r\n$body";
}
