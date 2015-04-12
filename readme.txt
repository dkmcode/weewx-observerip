observerip - weewx driver for the Ambient ObserverIP

INSTALLATION
1)
    Run the setup command from the WEEWX_ROOT directory.

    	setup.py install --extension weewx-observerip.tar.gz

2) modify weewx.conf:

   [Station]
	station_type = ObserverIP

   For other configuration options run
	bin/wee_config_device weewx.conf --defaultconfig

3) restart weewx


NOTES
The ObserverIP must be on the same network segment as the weewx server. UDP
broadcasts must be able to get from one to the other


In order to run in indirect mode change direct in the [ObserverIP] section of
weewx.conf to false. Copy util/apache/conf.d/weatherstation-intercept.conf
to the apache conifguration directory, /etc/httpd/conf.d on most systems. Make sure
the path in that file is reasonable. Create directory /var/www/weatherstation.
Copy util/apache/weatherstation/updateweatherstation.php to /var/www/weatherstation.
Edit both the updateweatherstation.php and weewx.conf. Set xferfile in each to point
to the same file. The file must be writable by the web server and readable by weewx.
Relative Pressure Offset in the calibration tab of the station setup must be set to 0.
