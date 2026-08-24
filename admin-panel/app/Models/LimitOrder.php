<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Model;

class LimitOrder extends Model
{
    protected $connection = 'exchange';
    protected $table = 'limit_orders';
    public $timestamps = false;
    protected $guarded = ['*'];
}
