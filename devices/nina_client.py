# %%

# Python 3.x version
import json
from urllib.parse import urlencode
from urllib.request import urlopen
from urllib.error import HTTPError


class NINA:
    """
    Client to the NINA control application for focuser control.

    API Documentation: https://bump.sh/christian-photo/doc/advanced-api/group/endpoint-focuser
    """

    def __init__(self, host="localhost", port=1888):
        self.host = host
        self.port = port
        self.base_url = f"http://{host}:{port}/v2/api/equipment/focuser"
        self.timeout_seconds = 10

    ### Focuser methods #################################

    def focuser_info(self):
        """
        Get the focuser info.

        Returns:
            dict: Focuser information including Position, Temperature, IsMoving,
                  Connected, Name, etc.
        """
        return self._request("/info")

    def focuser_connect(self, device_id=None):
        """
        Connect to Focuser.

        Args:
            device_id (str, optional): The Id of the device that should be connected.

        Returns:
            dict: Response with "Connected" message on success.
        """
        params = {}
        if device_id:
            params['to'] = device_id
        return self._request("/connect", **params)

    def focuser_disconnect(self):
        """
        Disconnect the focuser.

        Returns:
            dict: Response with "Disconnected" message on success.
        """
        return self._request("/disconnect")

    def focuser_list_devices(self):
        """
        List all devices which can be connected.

        Returns:
            dict: List of available focuser devices with their properties.
        """
        return self._request("/list-devices")

    def focuser_rescan(self):
        """
        Rescans for new devices, and returns a list of all available devices.

        Returns:
            dict: List of available focuser devices after rescan.
        """
        return self._request("/rescan")

    def focuser_goto(self, target):
        """
        Move the focuser to a specific position.

        Args:
            target (int): Position to move to.

        Returns:
            dict: Response with "Move started" message on success.
        """
        return self._request("/move", position=target)

    ### Autofocus methods #################################

    def autofocus_start(self):
        """
        Start an autofocus run.

        Returns:
            dict: Response with "Autofocus started" message on success.

        Raises:
            Exception: If focuser is not connected (409 error).
        """
        return self._request("/auto-focus")

    def autofocus_stop(self):
        """
        Cancel a running autofocus (if it was started using the API).

        Returns:
            dict: Response with "Autofocus canceled" message on success.
        """
        return self._request("/auto-focus", cancel=True)

    def autofocus_last(self):
        """
        Get last autofocus result.

        Returns:
            dict: Detailed autofocus result including Filter, Temperature,
                  Method, Fitting, MeasurePoints, Duration, etc.
        """
        return self._request("/last-af")

    ### Low-level request method ##################

    def _request(self, endpoint, **kwargs):
        """
        Issue a GET request to NINA API.

        Args:
            endpoint (str): API endpoint (e.g., "/info", "/move")
            **kwargs: Query parameters to include in the request.

        Returns:
            dict: Parsed JSON response from NINA.

        Raises:
            Exception: On HTTP errors or API errors.
        """
        url = self.base_url + endpoint

        if kwargs:
            # Convert boolean values to lowercase strings for URL
            params = {k: str(v).lower() if isinstance(v, bool) else v
                      for k, v in kwargs.items()}
            url += "?" + urlencode(params)

        try:
            response = urlopen(url, timeout=self.timeout_seconds)
            payload = response.read()
            result = json.loads(payload.decode('utf-8'))

            if not result.get('Success', False):
                error_msg = result.get('Error', 'Unknown error')
                raise Exception(f"NINA API error: {error_msg}")

            return result

        except HTTPError as e:
            error_message = f"NINA error: HTTP {e.code}"
            try:
                error_body = json.loads(e.read().decode('utf-8'))
                error_message = error_body.get('Error', error_message)
            except:
                pass
            raise Exception(error_message)

# %%
